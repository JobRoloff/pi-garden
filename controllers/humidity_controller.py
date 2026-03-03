"""
Humidity controller: maps DHT22 humidity readings to humidifier relay runtime.

Uses target low/high range and a control window; computes duration_s in [0, window_s]
when below target_low (proportional to deficit), and turns the relay off when in range
or above target_high.
"""

from __future__ import annotations

from typing import Any, Optional

from peripherals import DHT22
from peripherals.actuators.actuator import ActuatorCommand
from peripherals.actuators.relay import Relay
from peripherals.sensors.dht22 import DHTReading


class HumidityController:
    """
    Given a humidity sensor (DHT22) and a relay actuator, decides how long to run
    the humidifier each control window based on reading vs target range.
    """

    def __init__(
        self,
        actuator: Relay,
        target_low_pct: float,
        target_high_pct: float,
        control_window_s: float = 60.0,
    ):
        self.actuator = actuator
        self.target_low_pct = target_low_pct
        self.target_high_pct = target_high_pct
        self.control_window_s = control_window_s

    def _humidity_from_value(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, DHTReading):
            return value.humidity_pct
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            return float(value[1])
        return None

    def on_sample(self, sensor: Any, value: Any, ts: float) -> Optional[Any]:
        """
        Callback for the manager: only reacts to DHT22 samples. Computes actuation
        duration from humidity vs target range and returns a coroutine to run
        (actuator.apply), or None. Manager will await the result if it's a coroutine.
        """
        if not isinstance(sensor, DHT22):
            return None

        humidity = self._humidity_from_value(value)
        if humidity is None:
            return None

        # Above target: ensure relay is off
        if humidity >= self.target_high_pct:
            return self.actuator.apply(
                ActuatorCommand(value=False, reason="humidity at or above target")
            )

        # In range: no need to run
        if humidity >= self.target_low_pct:
            return self.actuator.apply(
                ActuatorCommand(value=False, reason="humidity in range")
            )

        # Below target: run proportionally to deficit, clamped to [0, control_window_s]
        deficit = self.target_low_pct - humidity
        # Scale by target_low so that humidity=0 -> full window (deficit/target_low = 1)
        if self.target_low_pct <= 0:
            duration_s = self.control_window_s
        else:
            ratio = deficit / self.target_low_pct
            duration_s = min(self.control_window_s, max(0.0, ratio * self.control_window_s))

        if duration_s <= 0:
            return self.actuator.apply(
                ActuatorCommand(value=False, reason="humidity control zero duration")
            )

        return self.actuator.apply(
            ActuatorCommand(
                value=True,
                duration_s=duration_s,
                reason=f"humidity {humidity:.1f}% below target (run {duration_s:.0f}s)",
            )
        )
