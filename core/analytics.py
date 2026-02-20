"""
analytics.py

A small, dependency-light analytics helper for greenhouse telemetry.

Supports:
- Rolling mean (O(1) update) and rolling median (simple, OK for small windows)
- EWMA (streaming exponential smoothing) with optional tau-based alpha
- Jump clamping (ignore one-sample glitches)
- Hysteresis + debounce + min on/off controller (good for humidifier)

Designed to be called every sample tick.

Key design choice:
- Analytics stays non-generic by ingesting normalized series values:
    update_series({"temp": 22.1, "humidity": 45.0}, now_ts=...)
- An adapter is responsible for mapping sensor-specific payloads into these series keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from statistics import median
from math import exp
from typing import Deque, Mapping, Optional, Tuple
import time


@dataclass
class HysteresisConfig:
    """
    Hysteresis controller config.

    Example for humidifier:
      - Turn ON when humidity < low
      - Turn OFF when humidity > high

    Add debounce and minimum on/off durations to avoid chatter.
    """
    low: float
    high: float
    debounce_sec: float = 0.0          # condition must hold this long before switching
    min_on_sec: float = 0.0            # once ON, stay ON at least this long
    min_off_sec: float = 0.0           # once OFF, stay OFF at least this long


@dataclass
class HysteresisState:
    is_on: bool = False
    last_change_ts: float = 0.0

    # When the "would like to switch" condition first became true
    pending_switch: Optional[bool] = None  # True means pending ON; False means pending OFF
    pending_since_ts: float = 0.0


class Analytics:
    """
    Streaming analytics + control logic.

    Typical usage per tick:
        a = Analytics(window=15, dt_sec=10, ewma_tau_sec=120)

        # Adapter normalizes payloads into named series
        a.update_series({"temp": 22.1, "humidity": 45.0}, now_ts=time.time())

        hum_mean = a.rolling_mean("humidity")
        hum_med  = a.rolling_median("humidity")
        hum_ewma = a.ewma("humidity")

        cmd, reason = a.hysteresis_humidifier_command(
            humidity_pct=a.raw["humidity"],
            now_ts=time.time(),
        )
    """

    def __init__(
        self,
        *,
        window: int = 15,
        dt_sec: float = 10.0,
        ewma_alpha: Optional[float] = None,
        ewma_tau_sec: Optional[float] = 120.0,
        clamp_jumps: Optional[Mapping[str, float]] = None,
        humidifier_cfg: Optional[HysteresisConfig] = None,
    ) -> None:
        if window <= 0:
            raise ValueError("window must be > 0")
        if dt_sec <= 0:
            raise ValueError("dt_sec must be > 0")

        self.window = window
        self.dt_sec = dt_sec

        # EWMA alpha: either user-provided, or derived from tau.
        if ewma_alpha is not None:
            if not (0.0 < ewma_alpha <= 1.0):
                raise ValueError("ewma_alpha must be in (0, 1]")
            self.ewma_alpha = float(ewma_alpha)
        else:
            # Default tau-based alpha, if tau provided; fallback alpha=0.2 otherwise.
            if ewma_tau_sec is not None and ewma_tau_sec > 0:
                self.ewma_alpha = 1.0 - exp(-dt_sec / ewma_tau_sec)
            else:
                self.ewma_alpha = 0.2

        # Jump clamp thresholds (absolute delta). Helps ignore one-sample glitches.
        # Example: {"humidity": 15.0, "temp": 5.0}
        self.clamp_jumps: dict[str, float] = dict(clamp_jumps or {})

        # Raw latest values (post-clamp)
        self.raw: dict[str, float] = {}
        self.actuators: dict[str, bool] = {}

        # Rolling windows / sums / ewma state are created lazily per-series
        self._windows: dict[str, Deque[float]] = {}
        self._sums: dict[str, float] = {}
        self._ewma: dict[str, Optional[float]] = {}

        # Hysteresis controller config/state for humidifier
        self.humidifier_cfg = humidifier_cfg or HysteresisConfig(
            low=55.0, high=62.0, debounce_sec=20.0, min_on_sec=60.0, min_off_sec=60.0
        )
        self.humidifier_state = HysteresisState(is_on=False, last_change_ts=0.0)

    def update_series(
        self,
        series: Mapping[str, float],
        *,
        now_ts: Optional[float] = None,
        actuators: Optional[Mapping[str, bool]] = None,
    ) -> None:
        """
        Ingest a batch of normalized series values for this tick.

        Example:
            update_series({"temp": 22.1, "humidity": 45.0}, now_ts=...)

        This keeps Analytics non-generic: the adapter maps sensor payloads -> series keys.
        """
        now = now_ts or time.time()

        if actuators:
            for k, v in actuators.items():
                self.actuators[k] = bool(v)

        for name, raw_val in series.items():
            v = float(raw_val)
            v = self._clamp_jump(name, v)
            self.raw[name] = v

            self._ensure_series(name)
            self._push_value(name, v)
            self._ewma_update(name, v)

        # (now is currently only used for external callers; stored state is in raw/windows)
        _ = now

    def update(
        self,
        *,
        temp_c: Optional[float] = None,
        humidity_pct: Optional[float] = None,
        humidifier_is_on: Optional[bool] = None,
        now_ts: Optional[float] = None,
    ) -> None:
        """
        Backwards-compatible convenience wrapper for common greenhouse signals.
        Prefer update_series(...) as you add more sensors.
        """
        series: dict[str, float] = {}
        if temp_c is not None:
            series["temp"] = float(temp_c)
        if humidity_pct is not None:
            series["humidity"] = float(humidity_pct)

        actuators: dict[str, bool] = {}
        if humidifier_is_on is not None:
            actuators["humidifier"] = bool(humidifier_is_on)

        self.update_series(series, now_ts=now_ts, actuators=actuators if actuators else None)

    def rolling_mean(self, series: str) -> Optional[float]:
        """Return rolling mean for `series` (any known series key)."""
        w = self._windows.get(series)
        if not w or len(w) == 0:
            return None
        return self._sums[series] / len(w)

    def rolling_median(self, series: str) -> Optional[float]:
        """Return rolling median for `series` (any known series key)."""
        w = self._windows.get(series)
        if not w or len(w) == 0:
            return None
        # For small windows (e.g., 5–31), this is totally fine.
        return float(median(w))

    def rollingMedian(self, series: str) -> Optional[float]:
        return self.rolling_median(series)

    def ewma(self, series: str) -> Optional[float]:
        """Return current EWMA value for `series`."""
        if series not in self._ewma:
            return None
        return self._ewma[series]

    def hysteresis(
        self,
        *,
        value: float,
        cfg: HysteresisConfig,
        state: HysteresisState,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Generic hysteresis controller with optional debounce and minimum on/off durations.
        Returns (new_is_on, reason).
        """
        now = now_ts or time.time()

        # Determine desired switch based on current state and thresholds
        desired: Optional[bool] = None
        if not state.is_on and value < cfg.low:
            desired = True
        elif state.is_on and value > cfg.high:
            desired = False

        # Respect min on/off time
        time_in_state = now - state.last_change_ts if state.last_change_ts > 0 else float("inf")
        if desired is True and state.is_on is False and time_in_state < cfg.min_off_sec:
            return state.is_on, f"hold_off_min_off({time_in_state:.1f}s<{cfg.min_off_sec}s)"
        if desired is False and state.is_on is True and time_in_state < cfg.min_on_sec:
            return state.is_on, f"hold_on_min_on({time_in_state:.1f}s<{cfg.min_on_sec}s)"

        # Debounce logic: require desired condition to persist
        if desired is None:
            # No switch requested; clear pending state
            state.pending_switch = None
            state.pending_since_ts = 0.0
            return state.is_on, "no_switch"

        if cfg.debounce_sec <= 0:
            # Switch immediately
            state.is_on = desired
            state.last_change_ts = now
            state.pending_switch = None
            state.pending_since_ts = 0.0
            return state.is_on, "switch_immediate"

        # Debounced switching:
        if state.pending_switch != desired:
            # New pending desire starts now
            state.pending_switch = desired
            state.pending_since_ts = now
            return state.is_on, "pending_started"

        # Same pending desire continues
        pending_for = now - state.pending_since_ts
        if pending_for >= cfg.debounce_sec:
            state.is_on = desired
            state.last_change_ts = now
            state.pending_switch = None
            state.pending_since_ts = 0.0
            return state.is_on, f"switch_debounced({pending_for:.1f}s)"

        return state.is_on, f"pending_wait({pending_for:.1f}s<{cfg.debounce_sec}s)"

    def hysteresis_humidifier_command(
        self,
        *,
        humidity_pct: float,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Convenience wrapper: returns the humidifier ON/OFF command given current humidity.
        """
        return self.hysteresis(
            value=float(humidity_pct),
            cfg=self.humidifier_cfg,
            state=self.humidifier_state,
            now_ts=now_ts,
        )

    def _ensure_series(self, series: str) -> None:
        if series in self._windows:
            return
        self._windows[series] = deque(maxlen=self.window)
        self._sums[series] = 0.0
        self._ewma[series] = None

    def _push_value(self, series: str, value: float) -> None:
        w = self._windows[series]

        # If deque is full, remove oldest from sum before append
        if len(w) == w.maxlen:
            oldest = w[0]
            self._sums[series] -= oldest

        w.append(value)
        self._sums[series] += value

    def _ewma_update(self, series: str, x: float) -> None:
        prev = self._ewma[series]
        if prev is None:
            self._ewma[series] = x
            return
        a = self.ewma_alpha
        self._ewma[series] = a * x + (1.0 - a) * prev

    def _clamp_jump(self, series: str, x: float) -> float:
        """
        If clamp_jumps[series] is set, clamp single-tick spikes by ignoring large jumps.
        """
        max_jump = self.clamp_jumps.get(series)
        if max_jump is None:
            return x
        prev = self.raw.get(series)
        if prev is None:
            return x
        if abs(x - prev) > float(max_jump):
            # Ignore this sample by returning previous
            return float(prev)
        return x