from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from src.config import AppConfig
from src.logger import setup_logger
from src.orderbook import OrderBook, OrderBookState
from src.wall_detector import SignalEvent, WallDetector
from src.ws_client import BinanceWsClient


class App:
    MIN_BUFFER_BEFORE_SNAPSHOT = 50
    SNAPSHOT_BUFFER_WAIT_TIMEOUT_SEC = 2.0
    SNAPSHOT_RETRY_DELAY_SEC = 0.7
    MAX_DEPTH_BUFFER = 5000
    RESYNC_BUFFER_KEEP = 2000

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.logger = setup_logger(cfg.log_file)
        self.orderbook = OrderBook(n_levels=cfg.n_levels)
        self.detector = WallDetector(
            n_levels=cfg.n_levels,
            wall_mult=cfg.wall_mult,
            min_wall_qty=cfg.min_wall_qty,
            max_wall_dist_bps=cfg.max_wall_dist_bps,
            event_ttl_sec=cfg.event_ttl_sec,
            wall_drop_pct=cfg.wall_drop_pct,
            imb_thr=cfg.imb_thr,
            signal_cooldown_sec=cfg.signal_cooldown_sec,
            max_touch_bps=cfg.max_touch_bps,
            price_cooldown_sec=cfg.price_cooldown_sec,
            full_remove_eps=cfg.full_remove_eps,
            only_full_remove=cfg.only_full_remove,
        )
        self.last_state = OrderBookState(bids=[], asks=[])
        self.last_imbalance = 0.0
        self.last_spread_bps = 0.0
        self.wall_candidates = 0
        self.last_update_id = 0
        self.synced = False
        self.resyncing = False
        self.depth_buffer: list[dict] = []
        self.state_lock = asyncio.Lock()
        self.snapshot_task: asyncio.Task | None = None

    async def on_connect(self) -> None:
        self.logger.info("Initializing local orderbook sync")
        async with self.state_lock:
            self.synced = False
            self.resyncing = True
            self.last_update_id = 0
            self.depth_buffer = []
            self.last_state = OrderBookState(bids=[], asks=[])
            self.detector.reset()
            self.orderbook.clear()
            if self.snapshot_task is not None:
                self.snapshot_task.cancel()
            self.snapshot_task = asyncio.create_task(self._bootstrap_snapshot())

    async def on_disconnect(self) -> None:
        async with self.state_lock:
            self.synced = False
            self.resyncing = False
            self.last_update_id = 0

    async def on_message(self, stream: str, data: dict) -> None:
        if stream != self.cfg.depth_stream:
            return

        async with self.state_lock:
            if not self.synced:
                self.depth_buffer.append(data)
                self._cap_depth_buffer_for_resync()
                return

            if not self._apply_depth_event(data):
                self.logger.warning("Depth gap detected, forcing resync")
                await self._start_resync_locked()
                return

            self._process_state_update()

    async def _bootstrap_snapshot(self) -> None:
        while True:
            try:
                await self._wait_for_buffer_before_snapshot()
                snapshot = await asyncio.to_thread(self._fetch_depth_snapshot)
                async with self.state_lock:
                    self.logger.info(
                        "Snapshot fetched | lastUpdateId=%s buffer_len=%d",
                        snapshot.get("lastUpdateId"),
                        len(self.depth_buffer),
                    )
                    if self._try_sync_from_snapshot(snapshot):
                        self.logger.info("Orderbook synchronized at updateId=%d", self.last_update_id)
                        self.resyncing = False
                        return
                self.logger.info("Snapshot sync attempt failed; retrying with accumulated buffer")
                await asyncio.sleep(self.SNAPSHOT_RETRY_DELAY_SEC)
            except Exception as exc:
                self.logger.warning("Snapshot bootstrap failed: %s", exc)
                await asyncio.sleep(1.0)

    async def _wait_for_buffer_before_snapshot(self) -> None:
        start = asyncio.get_running_loop().time()
        while True:
            async with self.state_lock:
                if self.synced:
                    return
                buffer_len = len(self.depth_buffer)
            if buffer_len >= self.MIN_BUFFER_BEFORE_SNAPSHOT:
                return
            if asyncio.get_running_loop().time() - start >= self.SNAPSHOT_BUFFER_WAIT_TIMEOUT_SEC:
                return
            await asyncio.sleep(0.05)

    def _fetch_depth_snapshot(self) -> dict:
        params = urlencode({"symbol": self.cfg.depth_stream.split("@")[0].upper(), "limit": self.cfg.snapshot_limit})
        url = f"{self.cfg.rest_depth_url}?{params}"
        with urlopen(url, timeout=10) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    def _try_sync_from_snapshot(self, snapshot: dict) -> bool:
        last_update_id = int(snapshot["lastUpdateId"])
        target = last_update_id + 1
        buffered = [event for event in self.depth_buffer if int(event.get("u", 0)) >= target]
        if not buffered:
            return False

        first_idx = -1
        for idx, event in enumerate(buffered):
            first_u = int(event.get("U", 0))
            final_u = int(event.get("u", 0))
            if first_u <= target <= final_u:
                first_idx = idx
                break

        if first_idx < 0:
            sample = buffered[:20]
            min_u = min((int(event.get("U", 0)) for event in sample), default=None)
            max_u = max((int(event.get("U", 0)) for event in sample), default=None)
            min_final = min((int(event.get("u", 0)) for event in sample), default=None)
            max_final = max((int(event.get("u", 0)) for event in sample), default=None)
            self.logger.warning(
                "Snapshot sync failed: no covering event for target=%d in buffer_len=%d (sample U=[%s..%s], u=[%s..%s])",
                target,
                len(buffered),
                min_u,
                max_u,
                min_final,
                max_final,
            )
            return False

        self.orderbook.load_snapshot(snapshot.get("bids", []), snapshot.get("asks", []))
        self.last_update_id = last_update_id

        first_event = buffered[first_idx]
        if not self._apply_depth_event_bootstrap(first_event, target):
            return False

        for event in buffered[first_idx + 1 :]:
            if not self._apply_depth_event(event):
                return False

        self.synced = True
        self.depth_buffer = [event for event in self.depth_buffer if int(event.get("u", 0)) > self.last_update_id]
        self._process_state_update()
        return True

    def _apply_depth_event(self, data: dict) -> bool:
        first_u = int(data.get("U", 0))
        final_u = int(data.get("u", 0))
        prev_u = int(data.get("pu", self.last_update_id))

        if final_u < self.last_update_id:
            return True
        if prev_u != self.last_update_id:
            self.logger.warning(
                "Depth event rejected: reason=prev_u_mismatch last_update_id=%d U=%d u=%d pu=%d",
                self.last_update_id,
                first_u,
                final_u,
                prev_u,
            )
            return False
        if not (first_u <= self.last_update_id + 1 <= final_u):
            self.logger.debug(
                "Depth event coverage mismatch (ignored): last_update_id=%d U=%d u=%d pu=%d",
                self.last_update_id,
                first_u,
                final_u,
                prev_u,
            )

        self.last_state = self.orderbook.apply_depth_update(data)
        self.last_update_id = final_u
        return True

    def _apply_depth_event_bootstrap(self, data: dict, target: int) -> bool:
        first_u = int(data.get("U", 0))
        final_u = int(data.get("u", 0))
        prev_u = int(data.get("pu", self.last_update_id))

        if not (first_u <= target <= final_u):
            self.logger.warning(
                "Bootstrap depth event rejected: reason=coverage_mismatch last_update_id=%d U=%d u=%d pu=%d target=%d",
                self.last_update_id,
                first_u,
                final_u,
                prev_u,
                target,
            )
            return False

        self.last_state = self.orderbook.apply_depth_update(data)
        self.last_update_id = final_u
        return True

    async def _start_resync_locked(self) -> None:
        self.synced = False
        self.resyncing = True
        self.last_update_id = 0
        self.orderbook.clear()
        self.detector.reset()
        self._cap_depth_buffer_for_resync()
        if self.snapshot_task is None or self.snapshot_task.done():
            self.snapshot_task = asyncio.create_task(self._bootstrap_snapshot())

    def _cap_depth_buffer_for_resync(self) -> None:
        if len(self.depth_buffer) <= self.MAX_DEPTH_BUFFER:
            return
        self.depth_buffer = self.depth_buffer[-self.RESYNC_BUFFER_KEEP :]

    def _process_state_update(self) -> None:
        events, imbalance, spread_bps, wall_candidates = self.detector.process(self.last_state, self.orderbook.qty_at)
        self.last_imbalance = imbalance
        self.last_spread_bps = spread_bps
        self.wall_candidates = wall_candidates
        for event in events:
            self._log_signal(event)

    async def heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.heartbeat_interval_sec)
            best_bid = self.last_state.bids[0][0] if self.last_state.bids else None
            best_ask = self.last_state.asks[0][0] if self.last_state.asks else None
            self.logger.info(
                "heartbeat | synced=%s best_bid=%s best_ask=%s imbalance=%.4f spread_bps=%.2f wall_candidates=%d buffer_len=%d",
                self.synced,
                f"{best_bid:.2f}" if best_bid is not None else "n/a",
                f"{best_ask:.2f}" if best_ask is not None else "n/a",
                self.last_imbalance,
                self.last_spread_bps,
                self.wall_candidates,
                len(self.depth_buffer),
            )

    def _log_signal(self, event: SignalEvent) -> None:
        self.logger.info(
            "SIGNAL %s | event=%s score=%d side=%s price=%.2f old_qty=%.4f current_qty=%.4f drop_pct=%.2f imbalance=%.4f dist_bps=%.2f best_bid=%.2f best_ask=%.2f touch_bps=%.2f ts=%.3f",
            event.direction,
            event.event_type,
            event.score,
            event.side,
            event.price,
            event.old_qty,
            event.current_qty,
            event.drop_pct,
            event.imbalance,
            event.dist_bps,
            event.best_bid,
            event.best_ask,
            event.touch_bps,
            event.ts,
        )


async def async_main() -> None:
    cfg = AppConfig()
    app = App(cfg)
    ws_client = BinanceWsClient(cfg=cfg, logger=app.logger)

    app.logger.info("Starting binance_wall_signal_bot")
    await asyncio.gather(
        ws_client.run(app.on_message, on_connect=app.on_connect, on_disconnect=app.on_disconnect),
        app.heartbeat_loop(),
    )


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Stopped by user at", time.strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    main()
