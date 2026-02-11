from __future__ import annotations

import asyncio
import time

from src.config import AppConfig
from src.logger import setup_logger
from src.orderbook import OrderBook, OrderBookState
from src.wall_detector import SignalEvent, WallDetector
from src.ws_client import BinanceWsClient


class App:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.logger = setup_logger(cfg.log_file)
        self.orderbook = OrderBook(n_levels=cfg.n_levels)
        self.detector = WallDetector(
            n_levels=cfg.n_levels,
            wall_mult=cfg.wall_mult,
            event_ttl_sec=cfg.event_ttl_sec,
            wall_drop_pct=cfg.wall_drop_pct,
            imb_thr=cfg.imb_thr,
        )
        self.last_state = OrderBookState(bids=[], asks=[])
        self.last_imbalance = 0.0

    async def on_message(self, stream: str, data: dict) -> None:
        if stream == self.cfg.depth_stream:
            state = self.orderbook.apply_depth_update(data)
            self.last_state = state
            events, imbalance = self.detector.process(state)
            self.last_imbalance = imbalance
            for event in events:
                self._log_signal(event)
        elif stream == self.cfg.agg_trade_stream:
            # Placeholder for future trade-based confirmations.
            return

    async def heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.heartbeat_interval_sec)
            best_bid = self.last_state.bids[0][0] if self.last_state.bids else None
            best_ask = self.last_state.asks[0][0] if self.last_state.asks else None
            self.logger.info(
                "heartbeat | best_bid=%s best_ask=%s imbalance=%.4f",
                f"{best_bid:.2f}" if best_bid is not None else "n/a",
                f"{best_ask:.2f}" if best_ask is not None else "n/a",
                self.last_imbalance,
            )

    def _log_signal(self, event: SignalEvent) -> None:
        self.logger.info(
            "SIGNAL %s | side=%s price=%.2f wall_qty=%.4f current_qty=%.4f drop_pct=%.2f imbalance=%.4f score=%d ts=%.3f",
            event.direction,
            event.side,
            event.price,
            event.wall_qty,
            event.current_qty,
            event.drop_pct,
            event.imbalance,
            event.score,
            event.ts,
        )


async def async_main() -> None:
    cfg = AppConfig()
    app = App(cfg)
    ws_client = BinanceWsClient(cfg=cfg, logger=app.logger)

    app.logger.info("Starting binance_wall_signal_bot")
    await asyncio.gather(ws_client.run(app.on_message), app.heartbeat_loop())


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Stopped by user at", time.strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    main()
