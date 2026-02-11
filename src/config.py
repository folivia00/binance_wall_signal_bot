from __future__ import annotations

from dataclasses import dataclass

WS_BASE_URL = "wss://fstream.binance.com/stream?streams="
SYMBOL = "btcusdt"

DEPTH_STREAM = f"{SYMBOL}@depth@100ms"
AGG_TRADE_STREAM = f"{SYMBOL}@aggTrade"
ENABLE_AGG_TRADE = False

N_LEVELS = 20
WALL_MULT = 5.0
EVENT_TTL_SEC = 2.0
WALL_DROP_PCT = 0.70
IMB_THR = 0.12
HEARTBEAT_INTERVAL_SEC = 2.0

LOG_FILE = "logs/signals.log"

RECONNECT_BASE_DELAY_SEC = 1.0
RECONNECT_MAX_DELAY_SEC = 30.0


@dataclass(frozen=True)
class AppConfig:
    ws_base_url: str = WS_BASE_URL
    depth_stream: str = DEPTH_STREAM
    agg_trade_stream: str = AGG_TRADE_STREAM
    enable_agg_trade: bool = ENABLE_AGG_TRADE
    n_levels: int = N_LEVELS
    wall_mult: float = WALL_MULT
    event_ttl_sec: float = EVENT_TTL_SEC
    wall_drop_pct: float = WALL_DROP_PCT
    imb_thr: float = IMB_THR
    heartbeat_interval_sec: float = HEARTBEAT_INTERVAL_SEC
    reconnect_base_delay_sec: float = RECONNECT_BASE_DELAY_SEC
    reconnect_max_delay_sec: float = RECONNECT_MAX_DELAY_SEC
    log_file: str = LOG_FILE


def stream_names(cfg: AppConfig) -> list[str]:
    streams = [cfg.depth_stream]
    if cfg.enable_agg_trade:
        streams.append(cfg.agg_trade_stream)
    return streams


def stream_url(cfg: AppConfig) -> str:
    joined = "/".join(stream_names(cfg))
    return f"{cfg.ws_base_url}{joined}"
