from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig
from src.main import App, _validate_ws_base_url
from src.pm_agent import PmAgent
from src.pm_rounds import PmRoundManager
from src.ws_client import BinanceWsClient


def _now_tag() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _mid(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


async def run_live(duration: int, tick_sec: float, outdir: Path) -> tuple[Path, Path]:
    cfg = AppConfig(heartbeat_interval_sec=max(1.0, tick_sec))
    _validate_ws_base_url(cfg.ws_base_url)
    app = App(cfg)
    ws_client = BinanceWsClient(cfg=cfg, logger=app.logger)
    agent = PmAgent(cfg)
    rounds = PmRoundManager(interval_sec=cfg.round_interval_sec)

    outdir.mkdir(parents=True, exist_ok=True)
    tag = _now_tag()
    csv_path = outdir / f"pm_sim_{tag}.csv"
    summary_path = outdir / f"pm_sim_{tag}_summary.json"

    columns = [
        "ts",
        "round_id",
        "ref_price",
        "t_left_sec",
        "mid",
        "best_bid",
        "best_ask",
        "p_up",
        "p_down",
        "base_raw",
        "base_p_up",
        "shock",
        "imbalance",
        "wall_candidates",
        "position",
        "action",
        "reason",
        "enter_long_thr",
        "enter_short_thr",
        "exit_thr",
        "rev_thr",
        "bias",
        "d_bps",
        "d_signed_bps",
        "t_frac",
        "trade_pnl",
        "round_pnl_running",
        "total_pnl_running",
    ]

    per_round: dict[int, dict[str, float | int]] = {}

    ws_task = asyncio.create_task(ws_client.run(app.on_message, on_connect=app.on_connect, on_disconnect=app.on_disconnect))
    hb_task = asyncio.create_task(app.heartbeat_loop())

    try:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            end_ts = time.time() + duration
            while time.time() < end_ts:
                await asyncio.sleep(tick_sec)
                async with app.state_lock:
                    bids = list(app.last_state.bids)
                    asks = list(app.last_state.asks)
                    score = app.last_score
                    imbalance = app.last_imbalance
                    wall_candidates = app.wall_candidates

                best_bid = bids[0][0] if bids else None
                best_ask = asks[0][0] if asks else None
                mid = _mid(best_bid, best_ask)
                if mid is None:
                    continue

                ts = time.time()
                round_state = rounds.on_tick(ts=ts, mid=mid, agent=agent)
                if round_state.round_id not in per_round:
                    per_round[round_state.round_id] = {
                        "round_id": round_state.round_id,
                        "ref_price": round_state.ref_price,
                        "round_pnl": 0.0,
                        "trades": 0,
                        "reversals": 0,
                    }

                result = agent.step(
                    ts=ts,
                    mid=mid,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    ref=round_state.ref_price,
                    t_left=round_state.t_left_sec,
                    p_up=score.p_up,
                    base_raw=score.base_raw,
                    base_p_up=score.base_p_up,
                    shock=score.shock_value,
                )

                if result.trade_close is not None:
                    info = per_round[round_state.round_id]
                    info["round_pnl"] = float(info["round_pnl"]) + result.trade_close.pnl
                    info["trades"] = int(info["trades"]) + 1
                    if result.action.startswith("REVERSE"):
                        info["reversals"] = int(info["reversals"]) + 1

                writer.writerow(
                    {
                        "ts": ts,
                        "round_id": round_state.round_id,
                        "ref_price": round_state.ref_price,
                        "t_left_sec": round_state.t_left_sec,
                        "mid": mid,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "p_up": score.p_up,
                        "p_down": score.p_down,
                        "base_raw": score.base_raw,
                        "base_p_up": score.base_p_up,
                        "shock": score.shock_value,
                        "imbalance": imbalance,
                        "wall_candidates": wall_candidates,
                        "position": agent.position.value,
                        "action": result.action,
                        "reason": result.reason,
                        "enter_long_thr": result.thresholds.enter_long_thr,
                        "enter_short_thr": result.thresholds.enter_short_thr,
                        "exit_thr": result.thresholds.exit_thr,
                        "rev_thr": result.thresholds.rev_thr,
                        "bias": result.thresholds.bias,
                        "d_bps": result.thresholds.d_bps,
                        "d_signed_bps": result.thresholds.d_signed_bps,
                        "t_frac": result.thresholds.t_frac,
                        "trade_pnl": result.trade_close.pnl if result.trade_close else "",
                        "round_pnl_running": agent.round_pnl,
                        "total_pnl_running": agent.total_pnl,
                    }
                )
                f.flush()
    finally:
        ws_task.cancel()
        hb_task.cancel()
        await asyncio.gather(ws_task, hb_task, return_exceptions=True)

    summary = {
        "rounds_count": len(per_round),
        "trades_count": agent.trades_count,
        "reversals_count": agent.reversals_count,
        "total_pnl": agent.total_pnl,
        "per_round": [per_round[key] for key in sorted(per_round.keys())],
    }
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return csv_path, summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Polymarket round paper simulator")
    parser.add_argument("--duration", type=int, default=300, help="Run duration in seconds")
    parser.add_argument("--tick-sec", type=float, default=1.0, help="Tick interval in seconds")
    parser.add_argument("--outdir", type=Path, default=Path("runs"), help="Output directory")
    args = parser.parse_args()

    try:
        csv_path, summary_path = asyncio.run(
            run_live(duration=max(1, args.duration), tick_sec=max(0.1, args.tick_sec), outdir=args.outdir)
        )
        print(f"csv={csv_path}")
        print(f"summary={summary_path}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
