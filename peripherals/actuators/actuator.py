from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar
import asyncio
import time

from gpiozero import DigitalOutputDevice

TState = TypeVar("TState")   # what the actuator's state/value type is (bool, float, int, etc.)
TMetric = TypeVar("TMetric") # whatever you use to identify the metric/series this actuator affects


@dataclass(frozen=True)
class ActuatorCommand(Generic[TState]):
    """
    A single intent to apply to an actuator.
    - value: desired actuator output/state (e.g., True for ON, 0.35 for PWM duty)
    - duration_s: optional. If set and value implies "active", the runner can turn it off after duration.
    - reason: human-friendly trace for logs/telemetry.
    - ts: timestamp (seconds since epoch). If omitted, Actuator will fill it.
    """
    value: TState
    duration_s: Optional[float] = None
    reason: str = ""
    ts: Optional[float] = None


class Actuator(ABC, Generic[TState, TMetric]):
    """
    Base class for actuators.

    Design goals:
    - "apply" is the main operation
    - optional "get_state" for verification/telemetry.
    - close/aclose + context managers for GPIO cleanup.
    - basic timing fields to support a scheduler/manager similar to sensors.
    """
    def __init__(self, name: str, metric: TMetric, frequency: float = 30.0):
        self.name = name
        self.metric: TMetric = metric
        self.frequency = float(frequency)

        self._closed = False

        # last known/applied state (for telemetry / idempotency / debouncing)
        self.state: Optional[TState] = None
        self.last_apply_ts: Optional[float] = None

    # ---- Core API ----
    async def apply(self, command: ActuatorCommand[TState]) -> None:
        """
        Apply a command to the actuator.

        This wrapper:
        - fills missing ts
        - stores last known state + timestamp
        - calls subclass hook _apply()
        """
        if self._closed:
            raise RuntimeError(f"Actuator '{self.name}' is closed")

        ts = command.ts if command.ts is not None else time.time()
        cmd = ActuatorCommand(
            value=command.value,
            duration_s=command.duration_s,
            reason=command.reason,
            ts=ts,
        )

        await self._apply(cmd)
        self.state = cmd.value
        self.last_apply_ts = ts

    @abstractmethod
    async def _apply(self, command: ActuatorCommand[TState]) -> None:
        """Subclass must implement the actual hardware interaction."""
        raise NotImplementedError

    async def get_state(self) -> Optional[TState]:
        """
        Optional: read back actuator state (if supported).
        Default returns cached state (last applied).
        Override for real hardware readback.
        """
        return self.state

    # ---- Cleanup hooks ----
    def _close(self) -> None:
        """Sync cleanup hook for subclasses (GPIO release, file close, etc.)."""
        return None

    async def _aclose(self) -> None:
        """Async cleanup hook for subclasses."""
        self._close()

    # ---- Public close API ----
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._aclose()

    # ---- Context manager support ----
    def __enter__(self) -> "Actuator[TState, TMetric]":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    async def __aenter__(self) -> "Actuator[TState, TMetric]":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()