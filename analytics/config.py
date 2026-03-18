import os

from dataclasses import dataclass
from math import exp
from dotenv import load_dotenv

from .env_helpers import (
    _env_bool,
    _env_float,
    _env_int,
    _env_opt_float,
    _parse_kv_floats,
)
from .hystersis.config import HysteresisConfig

@dataclass(frozen=True)
class AnalyticsConfig:
    dt_sec: float
    window: int
    buffer_max: int
    ewma_alpha: float
    clamp_jumps: dict[str, float]

    humidifier_enabled: bool
    humidifier_cfg: HysteresisConfig

    @classmethod
    def from_env(cls) -> "AnalyticsConfig":
        # This module is used by the running app (not as a library), so loading
        # env here keeps setup centralized.
        load_dotenv()

        # publish interval
        dt_sec = float(_env_float("ANALYTICS_DT_SEC", 60.0 * 5))
        if dt_sec <= 0:
            raise ValueError("ANALYTICS_DT_SEC must be > 0")

        # rolling window size (count of samples)
        window = int(_env_int("ANALYTICS_WINDOW", 15))
        if window <= 0:
            raise ValueError("ANALYTICS_WINDOW must be > 0")

        # per-interval buffer size (points, not seconds)
        buffer_max = int(_env_int("ANALYTICS_BUFFER_MAX", 5000))
        if buffer_max <= 0:
            raise ValueError("ANALYTICS_BUFFER_MAX must be > 0")

        # EWMA config
        ewma_alpha = _env_opt_float("ANALYTICS_EWMA_ALPHA")
        ewma_tau = _env_opt_float("ANALYTICS_EWMA_TAU_SEC")
        if ewma_alpha is not None:
            if not (0.0 < ewma_alpha <= 1.0):
                raise ValueError("ANALYTICS_EWMA_ALPHA must be in (0, 1]")
            ewma_alpha_f = float(ewma_alpha)
        else:
            # tau-based alpha with dt_sec; if tau missing, reasonable default
            if ewma_tau is not None and ewma_tau > 0:
                ewma_alpha_f = 1.0 - exp(-dt_sec / ewma_tau)
            else:
                ewma_alpha_f = 0.2

        # clamp thresholds
        clamp_str = os.getenv("ANALYTICS_CLAMP_JUMPS", "")
        clamp_jumps = _parse_kv_floats(clamp_str)

        # Optional humidifier controller config
        humidifier_enabled = _env_bool("HUMIDIFIER_ENABLED", False)
        humidifier_cfg = HysteresisConfig(
            low=_env_float("HUMIDIFIER_LOW", 55.0),
            high=_env_float("HUMIDIFIER_HIGH", 62.0),
            debounce_sec=_env_float("HUMIDIFIER_DEBOUNCE_SEC", 0.0),
            min_on_sec=_env_float("HUMIDIFIER_MIN_ON_SEC", 0.0),
            min_off_sec=_env_float("HUMIDIFIER_MIN_OFF_SEC", 0.0),
        )

        return cls(
            dt_sec=dt_sec,
            window=window,
            buffer_max=buffer_max,
            ewma_alpha=ewma_alpha_f,
            clamp_jumps=clamp_jumps,
            humidifier_enabled=humidifier_enabled,
            humidifier_cfg=humidifier_cfg,
        )