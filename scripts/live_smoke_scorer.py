from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.config import AppConfig
from src.main import App, _validate_ws_base_url
from src.ws_client import BinanceWsClient


async def run_smoke(duration_sec: int) -> None:
    cfg = AppConfig(heartbeat_interval_sec=1.0)
    _validate_ws_base_url(cfg.ws_base_url)
    app = App(cfg)
    ws_client = BinanceWsClient(cfg=cfg, logger=app.logger)

    ws_task = asyncio.create_task(ws_client.run(app.on_message, on_connect=app.on_connect, on_disconnect=app.on_disconnect))
    hb_task = asyncio.create_task(app.heartbeat_loop())

    try:
        await asyncio.sleep(duration_sec)
    except asyncio.CancelledError:
        pass
    finally:
        ws_task.cancel()
        hb_task.cancel()
        await asyncio.gather(ws_task, hb_task, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live scorer smoke check")
    parser.add_argument("--duration", type=int, default=90, help="Duration in seconds")
    args = parser.parse_args()
    try:
        asyncio.run(run_smoke(args.duration))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
