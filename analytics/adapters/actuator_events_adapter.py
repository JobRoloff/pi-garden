"""
Adapter that records actuator commands as time-series events in Analytics.

Wrap an actuator (e.g. Relay) with this adapter and pass the wrapper to your
controller. Each apply() is logged to analytics before delegating to the
underlying actuator, so you get a time series of events (on/off, reason, duration).
"""

from __future__ import annotations

import time
from typing import Any

from ..analytics import Analytics
from peripherals.actuators.actuator import Actuator, ActuatorCommand


class ActuatorEventsAdapter:
    """
    Wraps an actuator and records every apply() as an analytics event.
    Exposes the same interface the controller needs: name, metric, apply().
    """

    def __init__(self, actuator: Actuator[Any, Any], analytics: Analytics) -> None:
        self._actuator = actuator
        self._analytics = analytics

    @property
    def name(self) -> str:
        return self._actuator.name

    @property
    def metric(self) -> Any:
        return self._actuator.metric

    async def apply(self, command: ActuatorCommand[Any]) -> None:
        ts = command.ts if command.ts is not None else time.time()
        self._analytics.ingest_actuator_event(
            name=self._actuator.name,
            value=bool(command.value),
            reason=command.reason or "",
            ts=ts,
            duration_s=command.duration_s,
        )
        await self._actuator.apply(command)

    async def aclose(self) -> None:
        await self._actuator.aclose()
