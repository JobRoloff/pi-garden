"""
analytics.py

Temporarily holds raw + computed sensor data in memory and publishes to MQTT
every dt_sec (measured from the FIRST sample of an interval).

Design:
- Sensors call ingest_series(...) at their own cadence (e.g., every 30s).
- Each ingest appends a point into an in-memory deque buffer for the current interval.
- A flush loop waits until (interval_first_ts + dt_sec) and then:
    1) builds summary payload (ts, interval, latest, rollups, control) and publishes
       to the main topic via mqtt_publisher
    2) builds points payload (ts, interval, points) and publishes to the points
       topic via points_publisher
    3) resets interval markers and buffer
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Mapping, Optional, Tuple

from .config import AnalyticsConfig
from .env_helpers import _round2
from .hystersis.config import HysteresisConfig
from .hystersis.state import HysteresisState
from .rolling_stats import RollingStats

"""
A publisher can be called like a function. For this reason, we use the Callable type annotation.
The Callable type annotation takes 2 args: a list of arguments for the callable, a return type
A callable will be useful in this program for when we  
"""
Publisher = Callable[[dict], Awaitable[None]]


class Analytics:
    """
    Streaming analytics + interval buffering.

    Key idea:
      - Rolling metrics update per ingest (O(1) per series key).
      - Interval flush publishes every dt_sec, measured from the FIRST sample seen
        in that interval (so you don't publish empty windows if sampling pauses).
    """

    def __init__(
        self,
        mqtt_publisher: Optional[Publisher] = None,
        points_publisher: Optional[Publisher] = None,
        config: Optional[AnalyticsConfig] = None,
    ) -> None:
        self.config = config or AnalyticsConfig.from_env()

        # publish interval
        self.dt_sec = self.config.dt_sec

        # rolling window size (count of samples)
        self.window = self.config.window

        # per-interval buffer size (points, not seconds)
        self.buffer_max = self.config.buffer_max

        # EWMA config
        self.ewma_alpha = self.config.ewma_alpha

        # clamp thresholds
        self.clamp_jumps: dict[str, float] = self.config.clamp_jumps

        # Optional humidifier controller
        self.humidifier_enabled = self.config.humidifier_enabled
        self.humidifier_cfg = self.config.humidifier_cfg
        self.humidifier_state = HysteresisState(is_on=False, last_change_ts=0.0)

        # Latest raw values (post clamp)
        self.raw_latest: dict[str, float] = {}
        self.actuators_latest: dict[str, bool] = {}

        # Per-series rolling metrics (lazy)
        self._rolling = RollingStats(window=self.window, ewma_alpha=self.ewma_alpha)

        # Interval tracking
        self._interval_first_ts: Optional[float] = None
        self._interval_last_ts: Optional[float] = None
        self._interval_count: int = 0

        # Buffer of points for THIS interval
        # point schema (discriminated union):
        #   - Sensor reading:
        #       {
        #         "timestamp": <float>,
        #         "kind": "sensor_reading",
        #         "sensor_id": "<id>",
        #         "sensor_type": "<type>",
        #         "series": { <measurement_name>: <number>, ... },
        #         "actuators": { <actuator_id>: <bool|number>, ... },
        #       }
        #   - Actuator event:
        #       {
        #         "timestamp": <float>,
        #         "kind": "actuator_event",
        #         "actuator_id": "<id>",
        #         "value": <bool|number>,
        #         "reason": "<string>",
        #         "requested_duration_s": <float|null>,
        #       }
        self._buffer: Deque[dict[str, Any]] = deque(maxlen=self.buffer_max)

        # sinks: summary on main topic, raw points on points topic
        self._publisher: Optional[Publisher] = mqtt_publisher
        self._points_publisher: Optional[Publisher] = points_publisher

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
        sensor_id: Optional[str] = None,
        sensor_type: Optional[str] = None,
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

            self._rolling.update(name, v)

        # append a sensor_reading point to the interval buffer (only keys provided this tick)
        self._buffer.append(
            {
                "timestamp": now,
                "kind": "sensor_reading",
                "sensor_id": sensor_id,
                "sensor_type": sensor_type,
                "series": tick_series,
                "actuators": dict(self.actuators_latest),
            }
        )

    def ingest_actuator_event(
        self,
        name: str,
        value: bool,
        reason: str,
        ts: float,
        *,
        duration_s: Optional[float] = None,
    ) -> None:
        """
        Record a single actuator command as a time-series event.
        Use this when a controller applies a command (e.g. humidifier on/off).
        Events are appended to the same interval buffer as sensor points and
        published on the points topic, so downstream can correlate with sensor data.
        """
        self.actuators_latest[name] = value
        # append an actuator_event point to the interval buffer
        self._buffer.append(
            {
                "timestamp": ts,
                "kind": "actuator_event",
                "actuator_id": name,
                "value": value,
                "reason": reason,
                "requested_duration_s": _round2(duration_s) if duration_s is not None else None,
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

    # ---------------------------
    # Rollups / Accessors
    # ---------------------------
    def rolling_mean(self, series: str) -> Optional[float]:
        return self._rolling.mean(series)

    def rolling_median(self, series: str) -> Optional[float]:
        return self._rolling.median(series)

    def ewma(self, series: str) -> Optional[float]:
        return self._rolling.ewma(series)

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
                summary = self._build_summary_payload(include_interval=True)
                points_payload = self._build_points_payload()

                if self._publisher is not None:
                    try:
                        await self._publisher(summary)
                    except Exception as e:
                        print(f"[Analytics] publish error: {e}")

                if self._points_publisher is not None:
                    try:
                        await self._points_publisher(points_payload)
                    except Exception as e:
                        print(f"[Analytics] points publish error: {e}")

            # Reset interval + buffer
            self._interval_first_ts = None
            self._interval_last_ts = None
            self._interval_count = 0
            self._buffer.clear()

    def _build_summary_payload(self, include_interval: bool = True) -> dict[str, Any]:
        """
        Summary payload (main topic): ts, optional interval, latest readings, rollups, control.
        No points; use points topic for raw series.
        """
        series_keys = sorted(self._rolling.series_keys())
        rollups: dict[str, dict[str, Optional[float]]] = {}
        for k in series_keys:
            rollups[k] = {
                "mean": _round2(self.rolling_mean(k)),
                "median": _round2(self.rolling_median(k)),
                "ewma": _round2(self.ewma(k)),
            }

        cmd = self.humidifier_command(now_ts=self._interval_last_ts) if self.humidifier_enabled else None
        control: dict[str, Any] = {"actuators": dict(self.actuators_latest)}
        if cmd is not None:
            control["humidifier"] = {"is_on": cmd[0], "reason": cmd[1]}

        payload: dict[str, Any] = {
            "ts": round(time.time(), 2),
            "latest": dict(self.raw_latest),
            "rollups": rollups,
            "control": control,
        }
        if include_interval and self._interval_first_ts is not None and self._interval_last_ts is not None:
            payload["interval"] = {
                "first_ts": self._interval_first_ts,
                "last_ts": self._interval_last_ts,
                "sample_count": self._interval_count,
                "dt_sec": self.dt_sec,
            }
        return payload

    def _build_points_payload(self) -> dict[str, Any]:
        """Payload for points topic: ts, interval meta, and raw points array."""
        return {
            "ts": round(time.time(), 2),
            "interval": {
                "first_ts": self._interval_first_ts,
                "last_ts": self._interval_last_ts,
                "sample_count": self._interval_count,
                "dt_sec": self.dt_sec,
            },
            "points": list(self._buffer),
        }

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