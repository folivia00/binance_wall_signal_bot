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

AGENT_MODE = os.getenv("AGENT_MODE", "outcome").strip().lower()
OUTCOME_CONFIG_PATH = os.getenv("OUTCOME_CONFIG_PATH", "configs/outcome.yaml")

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

ROUND_INTERVAL_SEC = 15 * 60
REFERENCE_SOURCE = "mid"
PRESSURE_RANGES_BPS = (5.0, 10.0, 20.0)
PRESSURE_WEIGHTS = (1.0, 0.6, 0.3)
BASE_SCALE = 30.0
SHOCK_HALF_LIFE_SEC = 15.0
MAX_SHOCK = 35.0
SHOCK_DISTANCE_BPS_CAP = 20.0
SHOCK_MIN_AGE_SEC = 0.2
SHOCK_AGE_FULL_SEC = 1.0
BASE_CENTER_MODE = "blend"
BASE_REF_WEIGHT = 0.3
MIN_DEPTH_SUM = 1.0
SHOCK_DISTANCE_MODE = "blend"
SHOCK_FULL_REMOVE = 12.0
SHOCK_MAJOR_DROP = 7.0
SHOCK_DROP = 4.0

PM_BASE_ENTER = 52.0
PM_BASE_EXIT = 58.0
PM_BASE_REV = 75.0
PM_D0_BPS = 100.0
PM_BIAS_K = 8.0
PM_BIAS_M = 6.0
PM_BIAS_BMAX = 12.0
PM_EXIT_A = 8.0
PM_EXIT_B = 6.0
PM_REV_A = 20.0
PM_REV_B = 20.0
PM_COOLDOWN_SEC = 15.0

if PROFILE == "strict":
    MIN_WALL_QTY = 7.0
    MAX_WALL_DIST_BPS = 15.0
    EVENT_TTL_SEC = 2.0
    WALL_DROP_PCT = 0.98
    MAX_TOUCH_BPS = 2.0
    ONLY_FULL_REMOVE = True
    MIN_WALL_AGE_SEC = 0.40
    GLOBAL_COOLDOWN_SEC = 1.5

    BASE_SCALE = 20.0
    SHOCK_HALF_LIFE_SEC = 10.0
    MIN_DEPTH_SUM = 2.0
    BASE_REF_WEIGHT = 0.2
    SHOCK_FULL_REMOVE = 8.0
    SHOCK_MAJOR_DROP = 5.0
    SHOCK_DROP = 2.0
elif PROFILE == "balanced":
    MIN_WALL_QTY = 7.0
    MAX_WALL_DIST_BPS = 15.0
    EVENT_TTL_SEC = 2.0
    WALL_DROP_PCT = 0.92
    MAX_TOUCH_BPS = 2.0
    ONLY_FULL_REMOVE = False
    MIN_WALL_AGE_SEC = 0.25
    GLOBAL_COOLDOWN_SEC = 1.0

    BASE_SCALE = 30.0
    SHOCK_HALF_LIFE_SEC = 15.0
    MIN_DEPTH_SUM = 1.0
    BASE_REF_WEIGHT = 0.3
    SHOCK_FULL_REMOVE = 12.0
    SHOCK_MAJOR_DROP = 7.0
    SHOCK_DROP = 4.0
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
    agent_mode: str = AGENT_MODE
    outcome_config_path: str = OUTCOME_CONFIG_PATH
    snapshot_limit: int = SNAPSHOT_LIMIT
    round_interval_sec: int = ROUND_INTERVAL_SEC
    reference_source: str = REFERENCE_SOURCE
    pressure_ranges_bps: tuple[float, ...] = PRESSURE_RANGES_BPS
    pressure_weights: tuple[float, ...] = PRESSURE_WEIGHTS
    base_scale: float = BASE_SCALE
    shock_half_life_sec: float = SHOCK_HALF_LIFE_SEC
    max_shock: float = MAX_SHOCK
    shock_distance_bps_cap: float = SHOCK_DISTANCE_BPS_CAP
    shock_min_age_sec: float = SHOCK_MIN_AGE_SEC
    shock_age_full_sec: float = SHOCK_AGE_FULL_SEC
    min_depth_sum: float = MIN_DEPTH_SUM
    base_center_mode: str = BASE_CENTER_MODE
    base_ref_weight: float = BASE_REF_WEIGHT
    shock_distance_mode: str = SHOCK_DISTANCE_MODE
    shock_full_remove: float = SHOCK_FULL_REMOVE
    shock_major_drop: float = SHOCK_MAJOR_DROP
    shock_drop: float = SHOCK_DROP
    reconnect_base_delay_sec: float = RECONNECT_BASE_DELAY_SEC
    reconnect_max_delay_sec: float = RECONNECT_MAX_DELAY_SEC
    log_file: str = LOG_FILE
    rest_depth_url: str = REST_DEPTH_URL
    pm_base_enter: float = PM_BASE_ENTER
    pm_base_exit: float = PM_BASE_EXIT
    pm_base_rev: float = PM_BASE_REV
    pm_d0_bps: float = PM_D0_BPS
    pm_bias_k: float = PM_BIAS_K
    pm_bias_m: float = PM_BIAS_M
    pm_bias_bmax: float = PM_BIAS_BMAX
    pm_exit_a: float = PM_EXIT_A
    pm_exit_b: float = PM_EXIT_B
    pm_rev_a: float = PM_REV_A
    pm_rev_b: float = PM_REV_B
    pm_cooldown_sec: float = PM_COOLDOWN_SEC


def stream_names(cfg: AppConfig) -> list[str]:
    streams = [cfg.depth_stream]
    if cfg.enable_agg_trade:
        streams.append(cfg.agg_trade_stream)
    return streams


def stream_url(cfg: AppConfig) -> str:
    joined = "/".join(stream_names(cfg))
    return f"{cfg.ws_base_url}{joined}"
