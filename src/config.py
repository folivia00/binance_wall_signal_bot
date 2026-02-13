from __future__ import annotations

from dataclasses import dataclass
import os

WS_BASE_URL = "wss://fstream.binance.com/stream?streams="
SYMBOL = "btcusdt"
REST_DEPTH_URL = "https://fapi.binance.com/fapi/v1/depth"

DEPTH_STREAM = f"{SYMBOL}@depth@100ms"
AGG_TRADE_STREAM = f"{SYMBOL}@aggTrade"
ENABLE_AGG_TRADE = False

PROFILE = os.getenv("PROFILE", "balanced").strip().lower()

N_LEVELS = 100
WALL_MULT = 5.0
IMB_THR = 0.12
HEARTBEAT_INTERVAL_SEC = 2.0
SIGNAL_COOLDOWN_SEC = 10.0
PRICE_COOLDOWN_SEC = 60.0
PRICE_BUCKET = 0.1
MIN_TOUCH_BPS = 0.0
FULL_REMOVE_EPS = 1e-6
MAJOR_DROP_MIN_PCT = 0.95
GLOBAL_COOLDOWN_SEC = 1.0
SNAPSHOT_LIMIT = 1000

if PROFILE == "strict":
    MIN_WALL_QTY = 7.0
    MAX_WALL_DIST_BPS = 15.0
    EVENT_TTL_SEC = 2.0
    WALL_DROP_PCT = 0.98
    MAX_TOUCH_BPS = 2.0
    ONLY_FULL_REMOVE = True
    MIN_WALL_AGE_SEC = 0.40
    GLOBAL_COOLDOWN_SEC = 1.5
elif PROFILE == "balanced":
    MIN_WALL_QTY = 7.0
    MAX_WALL_DIST_BPS = 15.0
    EVENT_TTL_SEC = 2.0
    WALL_DROP_PCT = 0.92
    MAX_TOUCH_BPS = 2.0
    ONLY_FULL_REMOVE = False
    MIN_WALL_AGE_SEC = 0.25
    GLOBAL_COOLDOWN_SEC = 1.0
else:
    raise ValueError(f"Unsupported PROFILE='{PROFILE}'. Use 'balanced' or 'strict'.")


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
    min_wall_qty: float = MIN_WALL_QTY
    max_wall_dist_bps: float = MAX_WALL_DIST_BPS
    event_ttl_sec: float = EVENT_TTL_SEC
    wall_drop_pct: float = WALL_DROP_PCT
    imb_thr: float = IMB_THR
    heartbeat_interval_sec: float = HEARTBEAT_INTERVAL_SEC
    signal_cooldown_sec: float = SIGNAL_COOLDOWN_SEC
    max_touch_bps: float = MAX_TOUCH_BPS
    min_touch_bps: float = MIN_TOUCH_BPS
    price_cooldown_sec: float = PRICE_COOLDOWN_SEC
    price_bucket: float = PRICE_BUCKET
    full_remove_eps: float = FULL_REMOVE_EPS
    only_full_remove: bool = ONLY_FULL_REMOVE
    major_drop_min_pct: float = MAJOR_DROP_MIN_PCT
    min_wall_age_sec: float = MIN_WALL_AGE_SEC
    global_cooldown_sec: float = GLOBAL_COOLDOWN_SEC
    profile: str = PROFILE
    snapshot_limit: int = SNAPSHOT_LIMIT
    reconnect_base_delay_sec: float = RECONNECT_BASE_DELAY_SEC
    reconnect_max_delay_sec: float = RECONNECT_MAX_DELAY_SEC
    log_file: str = LOG_FILE
    rest_depth_url: str = REST_DEPTH_URL


def stream_names(cfg: AppConfig) -> list[str]:
    streams = [cfg.depth_stream]
    if cfg.enable_agg_trade:
        streams.append(cfg.agg_trade_stream)
    return streams


def stream_url(cfg: AppConfig) -> str:
    joined = "/".join(stream_names(cfg))
    return f"{cfg.ws_base_url}{joined}"
