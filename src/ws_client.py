from __future__ import annotations

import asyncio
import json
import logging

import websockets
from websockets import WebSocketException

from src.config import AppConfig, stream_url


class BinanceWsClient:
    def __init__(self, cfg: AppConfig, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.logger = logger

    async def run(self, handler, on_connect=None, on_disconnect=None) -> None:
        delay = self.cfg.reconnect_base_delay_sec
        url = stream_url(self.cfg)

        while True:
            try:
                self.logger.info("Connecting to %s", url)
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self.logger.info("WebSocket connected")
                    if on_connect is not None:
                        await on_connect()
                    delay = self.cfg.reconnect_base_delay_sec
                    async for message in ws:
                        payload = json.loads(message)
                        stream = payload.get("stream", "")
                        data = payload.get("data", {})
                        await handler(stream, data)
            except (ConnectionError, OSError, asyncio.TimeoutError, WebSocketException, json.JSONDecodeError) as exc:
                if on_disconnect is not None:
                    await on_disconnect()
                self.logger.warning("WebSocket disconnected: %s", exc)
                self.logger.info("Reconnecting in %.1f sec", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.cfg.reconnect_max_delay_sec)
