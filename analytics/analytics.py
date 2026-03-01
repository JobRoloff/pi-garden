"""
analytics.py

Temporarily holds raw + computed sensor data in memory and publishes rollups
to MQTT every dt_sec (measured from the FIRST sample of an interval).

Design:
- Sensors call ingest_series(...) at their own cadence (e.g., every 30s).
- Each ingest appends a point into an in-memory deque buffer for the current interval.
- A flush loop waits until (interval_first_ts + dt_sec) and then:
    1) builds rollups (mean/median/ewma) + controller suggestion
    2) includes the buffered points
    3) publishes payload via the provided async publisher
- After publishing, the interval markers and buffer are reset.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from collections import deque
from math import exp
from statistics import median
from typing import Any, Awaitable, Callable, Deque, Mapping, Optional, Tuple

from dotenv import load_dotenv

# --- Types ---
Publisher = Callable[[dict], Awaitable[None]]  # async sink for flush payloads


# --- Helpers ---
def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    return default if v is None else int(v)


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    return default if v is None else float(v)


def _env_opt_float(key: str) -> Optional[float]:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return None
    return float(v)


def _parse_kv_floats(s: str) -> dict[str, float]:
    """
    Parse "temp=5,humidity=15" -> {"temp": 5.0, "humidity": 15.0}
    """
    out: dict[str, float] = {}
    s = s.strip()
    if not s:
        return out
    parts = [p.strip() for p in s.split(",") if p.strip()]
    for p in parts:
        if "=" not in p:
            raise ValueError(f"Invalid clamp entry '{p}'. Use key=value.")
        k, v = p.split("=", 1)
        out[k.strip()] = float(v.strip())
    return out


# --- Controller config/state ---
@dataclass
class HysteresisConfig:
    low: float
    high: float
    debounce_sec: float = 0.0
    min_on_sec: float = 0.0
    min_off_sec: float = 0.0


@dataclass
class HysteresisState:
    is_on: bool = False
    last_change_ts: float = 0.0
    pending_switch: Optional[bool] = None
    pending_since_ts: float = 0.0


class Analytics:
    """
    Streaming analytics + interval buffering.

    Key idea:
      - Rolling metrics update per ingest (O(1) per series key).
      - Interval flush publishes every dt_sec, measured from the FIRST sample seen
        in that interval (so you don't publish empty windows if sampling pauses).
    """

    def __init__(self, mqtt_publisher: Optional[Publisher] = None) -> None:
        load_dotenv()

        # publish interval
        self.dt_sec = float(_env_float("ANALYTICS_DT_SEC", 60.0 * 5))
        if self.dt_sec <= 0:
            raise ValueError("ANALYTICS_DT_SEC must be > 0")

        # rolling window size (count of samples)
        self.window = int(_env_int("ANALYTICS_WINDOW", 15))
        if self.window <= 0:
            raise ValueError("ANALYTICS_WINDOW must be > 0")

        # per-interval buffer size (points, not seconds)
        self.buffer_max = int(_env_int("ANALYTICS_BUFFER_MAX", 5000))
        if self.buffer_max <= 0:
            raise ValueError("ANALYTICS_BUFFER_MAX must be > 0")

        # EWMA config
        ewma_alpha = _env_opt_float("ANALYTICS_EWMA_ALPHA")
        ewma_tau = _env_opt_float("ANALYTICS_EWMA_TAU_SEC")
        if ewma_alpha is not None:
            if not (0.0 < ewma_alpha <= 1.0):
                raise ValueError("ANALYTICS_EWMA_ALPHA must be in (0, 1]")
            self.ewma_alpha = float(ewma_alpha)
        else:
            # tau-based alpha with dt_sec; if tau missing, reasonable default
            if ewma_tau is not None and ewma_tau > 0:
                self.ewma_alpha = 1.0 - exp(-self.dt_sec / ewma_tau)
            else:
                self.ewma_alpha = 0.2

        # clamp thresholds
        clamp_str = os.getenv("ANALYTICS_CLAMP_JUMPS", "")
        self.clamp_jumps: dict[str, float] = _parse_kv_floats(clamp_str)

        # Optional humidifier controller
        self.humidifier_enabled = _env_bool("HUMIDIFIER_ENABLED", False)
        self.humidifier_cfg = HysteresisConfig(
            low=_env_float("HUMIDIFIER_LOW", 55.0),
            high=_env_float("HUMIDIFIER_HIGH", 62.0),
            debounce_sec=_env_float("HUMIDIFIER_DEBOUNCE_SEC", 0.0),
            min_on_sec=_env_float("HUMIDIFIER_MIN_ON_SEC", 0.0),
            min_off_sec=_env_float("HUMIDIFIER_MIN_OFF_SEC", 0.0),
        )
        self.humidifier_state = HysteresisState(is_on=False, last_change_ts=0.0)

        # Latest raw values (post clamp)
        self.raw_latest: dict[str, float] = {}
        self.actuators_latest: dict[str, bool] = {}

        # Per-series rolling structures (lazy)
        self._windows: dict[str, Deque[float]] = {}
        self._sums: dict[str, float] = {}
        self._ewma: dict[str, Optional[float]] = {}

        # Interval tracking
        self._interval_first_ts: Optional[float] = None
        self._interval_last_ts: Optional[float] = None
        self._interval_count: int = 0

        # Buffer of points for THIS interval
        # point schema: {"ts": float, "series": {k: float}, "actuators": {k: bool}}
        self._buffer: Deque[dict[str, Any]] = deque(maxlen=self.buffer_max)

        # sink
        self._publisher: Optional[Publisher] = mqtt_publisher

        # loop control
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    # ---------------------------
    # Public API
    # ---------------------------
    def ingest_series(
        self,
        series: Mapping[str, float],
        *,
        now_ts: Optional[float] = None,
        actuators: Optional[Mapping[str, bool]] = None,
    ) -> None:
        """
        Ingest normalized series values for this tick.
        O(1) per series key.

        Example:
          ingest_series({"temp": 22.1, "humidity": 45.0}, now_ts=ts)
        """
        now = now_ts or time.time()

        # interval markers
        if self._interval_first_ts is None:
            self._interval_first_ts = now
        self._interval_last_ts = now
        self._interval_count += 1

        # update latest actuator states first
        if actuators:
            for k, v in actuators.items():
                self.actuators_latest[k] = bool(v)

        # ingest / clamp / update rolling stats
        tick_series: dict[str, float] = {}
        for name, raw_val in series.items():
            v = float(raw_val)
            v = self._clamp_jump(name, v)

            self.raw_latest[name] = v
            tick_series[name] = v

            self._ensure_series(name)
            self._push_value(name, v)
            self._ewma_update(name, v)

        # append a point to the interval buffer (only keys provided this tick)
        self._buffer.append(
            {
                "ts": now,
                "series": tick_series,
                "actuators": dict(self.actuators_latest),
            }
        )

    async def start(self) -> None:
        """Start the periodic flush loop."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the periodic flush loop."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            await asyncio.gather(self._flush_task, return_exceptions=True)
            self._flush_task = None

    def snapshot(self) -> dict[str, Any]:
        """
        Current analytics snapshot (no publishing).
        """
        return self._build_payload(include_interval_meta=False, include_points=False)

    # ---------------------------
    # Rollups / Accessors
    # ---------------------------
    def rolling_mean(self, series: str) -> Optional[float]:
        w = self._windows.get(series)
        if not w:
            return None
        return self._sums[series] / len(w)

    def rolling_median(self, series: str) -> Optional[float]:
        w = self._windows.get(series)
        if not w:
            return None
        return float(median(w))

    def ewma(self, series: str) -> Optional[float]:
        return self._ewma.get(series)

    # ---------------------------
    # Humidifier controller (optional)
    # ---------------------------
    def humidifier_command(self, *, now_ts: Optional[float] = None) -> Optional[Tuple[bool, str]]:
        """
        If enabled and humidity is known, returns (command_is_on, reason).
        Otherwise returns None.
        """
        if not self.humidifier_enabled:
            return None
        humidity = self.raw_latest.get("humidity")
        if humidity is None:
            return None
        return self._hysteresis(
            value=float(humidity),
            cfg=self.humidifier_cfg,
            state=self.humidifier_state,
            now_ts=now_ts,
        )

    # ---------------------------
    # Internals
    # ---------------------------
    async def _flush_loop(self) -> None:
        """
        Flush when (interval_first_ts + dt_sec) is reached.
        If no samples arrived, it waits.
        """
        print("[Analytics] flush loop running")
        while self._running:
            # Wait for at least one sample to start an interval
            if self._interval_first_ts is None:
                await asyncio.sleep(0.05)
                continue

            due_at = self._interval_first_ts + self.dt_sec
            now = time.time()
            sleep_for = max(0.0, due_at - now)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

            # It might have been reset while sleeping
            if self._interval_first_ts is None:
                continue

            # Only publish if we actually collected samples
            if self._interval_count > 0:
                payload = self._build_payload(include_interval_meta=True, include_points=True)

                if self._publisher is not None:
                    try:
                        await self._publisher(payload)
                    except Exception as e:
                        # Keep loop alive; you can add retries/backoff later.
                        print(f"[Analytics] publish error: {e}")

            # Reset interval + buffer
            self._interval_first_ts = None
            self._interval_last_ts = None
            self._interval_count = 0
            self._buffer.clear()

    def _build_payload(self, include_interval_meta: bool, include_points: bool) -> dict[str, Any]:
        """
        Payload includes:
          - raw_latest
          - per-series rolling mean/median/ewma
          - latest actuator states
          - optional humidifier command recommendation
          - optional interval meta (first/last ts, sample_count, dt_sec)
          - optional points (the per-tick samples collected during the interval)
        """
        series_keys = sorted(self._windows.keys())

        rollups: dict[str, dict[str, Optional[float]]] = {}
        for k in series_keys:
            rollups[k] = {
                "mean": self.rolling_mean(k),
                "median": self.rolling_median(k),
                "ewma": self.ewma(k),
            }

        cmd = self.humidifier_command(now_ts=self._interval_last_ts) if self.humidifier_enabled else None

        payload: dict[str, Any] = {
            "ts": time.time(),
            "raw_latest": dict(self.raw_latest),
            "actuators_latest": dict(self.actuators_latest),
            "rollups": rollups,
        }

        if cmd is not None:
            payload["humidifier_command"] = {"is_on": cmd[0], "reason": cmd[1]}

        if include_interval_meta:
            payload["interval"] = {
                "first_ts": self._interval_first_ts,
                "last_ts": self._interval_last_ts,
                "sample_count": self._interval_count,
                "dt_sec": self.dt_sec,
            }

        if include_points:
            payload["points"] = list(self._buffer)

        return payload

    def _ensure_series(self, series: str) -> None:
        if series in self._windows:
            return
        self._windows[series] = deque(maxlen=self.window)
        self._sums[series] = 0.0
        self._ewma[series] = None

    def _push_value(self, series: str, value: float) -> None:
        w = self._windows[series]
        if len(w) == w.maxlen:
            self._sums[series] -= w[0]
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
        If clamp_jumps[series] is set, clamp one-sample spikes by ignoring large jumps.
        """
        max_jump = self.clamp_jumps.get(series)
        if max_jump is None:
            return x
        prev = self.raw_latest.get(series)
        if prev is None:
            return x
        if abs(x - prev) > float(max_jump):
            return float(prev)
        return x

    def _hysteresis(
        self,
        *,
        value: float,
        cfg: HysteresisConfig,
        state: HysteresisState,
        now_ts: Optional[float] = None,
    ) -> Tuple[bool, str]:
        now = now_ts or time.time()

        desired: Optional[bool] = None
        if not state.is_on and value < cfg.low:
            desired = True
        elif state.is_on and value > cfg.high:
            desired = False

        time_in_state = now - state.last_change_ts if state.last_change_ts > 0 else float("inf")
        if desired is True and not state.is_on and time_in_state < cfg.min_off_sec:
            return state.is_on, f"hold_off_min_off({time_in_state:.1f}s<{cfg.min_off_sec}s)"
        if desired is False and state.is_on and time_in_state < cfg.min_on_sec:
            return state.is_on, f"hold_on_min_on({time_in_state:.1f}s<{cfg.min_on_sec}s)"

        if desired is None:
            state.pending_switch = None
            state.pending_since_ts = 0.0
            return state.is_on, "no_switch"

        if cfg.debounce_sec <= 0:
            state.is_on = desired
            state.last_change_ts = now
            state.pending_switch = None
            state.pending_since_ts = 0.0
            return state.is_on, "switch_immediate"

        if state.pending_switch != desired:
            state.pending_switch = desired
            state.pending_since_ts = now
            return state.is_on, "pending_started"

        pending_for = now - state.pending_since_ts
        if pending_for >= cfg.debounce_sec:
            state.is_on = desired
            state.last_change_ts = now
            state.pending_switch = None
            state.pending_since_ts = 0.0
            return state.is_on, f"switch_debounced({pending_for:.1f}s)"

        return state.is_on, f"pending_wait({pending_for:.1f}s<{cfg.debounce_sec}s)"