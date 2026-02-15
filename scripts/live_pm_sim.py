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
from src.pm_agent import PmAgent, PmTickSnapshot
from src.pm_round_manager import PmRoundManager
from src.ws_client import BinanceWsClient


def _now_tag() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _default_out_path() -> Path:
    Path("runs").mkdir(parents=True, exist_ok=True)
    return Path("runs") / f"pm_sim_{_now_tag()}.csv"


def _summary_path_from_csv(path: Path) -> Path:
    return path.with_name(f"{path.stem}_summary.json")


def _mid(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


async def run_live(duration: int, out_path: Path, tick_sec: float) -> None:
    cfg = AppConfig(heartbeat_interval_sec=max(1.0, tick_sec))
    _validate_ws_base_url(cfg.ws_base_url)
    app = App(cfg)
    ws_client = BinanceWsClient(cfg=cfg, logger=app.logger)
    round_manager = PmRoundManager(round_interval_sec=cfg.round_interval_sec)
    agent = PmAgent()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = _summary_path_from_csv(out_path)

    columns = [
        "ts",
        "round_id",
        "ref_price",
        "t_left_sec",
        "mid",
        "best_bid",
        "best_ask",
        "p_up",
        "base_raw",
        "base_p_up",
        "shock",
        "position",
        "action",
        "reason",
        "rev_thr",
        "d_bps",
        "t_frac",
    ]

    ws_task = asyncio.create_task(ws_client.run(app.on_message, on_connect=app.on_connect, on_disconnect=app.on_disconnect))
    hb_task = asyncio.create_task(app.heartbeat_loop())

    final_mid: float | None = None
    final_ts: float | None = None

    try:
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            end_ts = time.time() + duration
            while time.time() < end_ts:
                await asyncio.sleep(tick_sec)
                async with app.state_lock:
                    bids = list(app.last_state.bids)
                    asks = list(app.last_state.asks)
                    score = app.last_score

                best_bid = bids[0][0] if bids else None
                best_ask = asks[0][0] if asks else None
                mid = _mid(best_bid, best_ask)
                if mid is None:
                    continue

                now = time.time()
                round_state = round_manager.on_tick(mid=mid, ts=now)
                action = agent.on_tick(
                    PmTickSnapshot(
                        round_id=round_state.round_id,
                        ref_price=round_state.ref_price,
                        t_left_sec=round_state.t_left_sec,
                        d_bps=round_state.d_bps,
                        t_frac=round_state.t_frac,
                        mid=mid,
                    ),
                    score=score,
                    ts=now,
                )

                final_mid = mid
                final_ts = now
                writer.writerow(
                    {
                        "ts": now,
                        "round_id": round_state.round_id,
                        "ref_price": round_state.ref_price,
                        "t_left_sec": round_state.t_left_sec,
                        "mid": mid,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "p_up": score.p_up,
                        "base_raw": score.base_raw,
                        "base_p_up": score.base_p_up,
                        "shock": score.shock_value,
                        "position": agent.position.value,
                        "action": action.name,
                        "reason": action.reason,
                        "rev_thr": action.rev_thr,
                        "d_bps": round_state.d_bps,
                        "t_frac": round_state.t_frac,
                    }
                )
                f.flush()
    finally:
        ws_task.cancel()
        hb_task.cancel()
        await asyncio.gather(ws_task, hb_task, return_exceptions=True)

    summary = agent.summarize(final_mid=final_mid, final_ts=final_ts)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def run_from_log(in_path: Path, out_path: Path) -> None:
    round_manager = PmRoundManager(round_interval_sec=15 * 60)
    agent = PmAgent()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "ts",
        "round_id",
        "ref_price",
        "t_left_sec",
        "mid",
        "best_bid",
        "best_ask",
        "p_up",
        "base_raw",
        "base_p_up",
        "shock",
        "position",
        "action",
        "reason",
        "rev_thr",
        "d_bps",
        "t_frac",
    ]

    final_mid: float | None = None
    final_ts: float | None = None

    with in_path.open("r", encoding="utf-8") as src, out_path.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=columns)
        writer.writeheader()
        for row in reader:
            ts = float(row["ts"])
            mid = float(row["mid"])
            p_up = float(row["p_up"])
            base_raw = float(row.get("base_raw", 0.0))
            base_p_up = float(row.get("base_p_up", 50.0))
            shock = float(row.get("shock", 0.0))
            best_bid = float(row.get("best_bid", mid))
            best_ask = float(row.get("best_ask", mid))

            from src.polymarket_scorer import ScoreSnapshot

            score = ScoreSnapshot(
                p_up=p_up,
                p_down=100.0 - p_up,
                base_raw=base_raw,
                base_p_up=base_p_up,
                shock_value=shock,
                ref_price=0.0,
                round_id="",
                pressure_breakdown=[],
            )
            round_state = round_manager.on_tick(mid=mid, ts=ts)
            action = agent.on_tick(
                PmTickSnapshot(
                    round_id=round_state.round_id,
                    ref_price=round_state.ref_price,
                    t_left_sec=round_state.t_left_sec,
                    d_bps=round_state.d_bps,
                    t_frac=round_state.t_frac,
                    mid=mid,
                ),
                score,
                ts,
            )
            writer.writerow(
                {
                    "ts": ts,
                    "round_id": round_state.round_id,
                    "ref_price": round_state.ref_price,
                    "t_left_sec": round_state.t_left_sec,
                    "mid": mid,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "p_up": p_up,
                    "base_raw": base_raw,
                    "base_p_up": base_p_up,
                    "shock": shock,
                    "position": agent.position.value,
                    "action": action.name,
                    "reason": action.reason,
                    "rev_thr": action.rev_thr,
                    "d_bps": round_state.d_bps,
                    "t_frac": round_state.t_frac,
                }
            )
            final_mid = mid
            final_ts = ts

    summary = agent.summarize(final_mid=final_mid, final_ts=final_ts)
    with _summary_path_from_csv(out_path).open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Polymarket paper simulator")
    parser.add_argument("--duration", type=int, default=300, help="Live mode duration in seconds")
    parser.add_argument("--tick", type=float, default=1.0, help="Sampling interval in seconds")
    parser.add_argument("--out", type=Path, default=None, help="Output CSV path")
    parser.add_argument("--input", type=Path, default=None, help="Replay from input CSV log")
    args = parser.parse_args()

    out_path = args.out or _default_out_path()

    if args.input:
        run_from_log(args.input, out_path)
        return

    try:
        asyncio.run(run_live(duration=args.duration, out_path=out_path, tick_sec=max(1.0, args.tick)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
