from __future__ import annotations

import asyncio
from typing import Optional

from gpiozero import DigitalOutputDevice

from .actuator import Actuator, ActuatorCommand, TMetric


class Relay(Actuator[bool, TMetric]):
    """
    Simple GPIO-backed relay actuator.

    Controllers are expected to compute a duration in seconds per control
    window and pass it via ActuatorCommand.duration_s; this class just turns
    the relay on for that duration and then off again.
    """

    def __init__(
        self,
        name: str,
        metric: TMetric,
        gpio_pin: int,
        *,
        active_high: bool = True,
        initial_value: bool = False,
        max_duration_s: Optional[float] = None,
    ):
        super().__init__(name=name, metric=metric)
        self._device = DigitalOutputDevice(
            gpio_pin, active_high=active_high, initial_value=initial_value
        )
        self._max_duration_s = max_duration_s
        self._current_task: Optional[asyncio.Task] = None

    async def _apply(self, command: ActuatorCommand[bool]) -> None:
        # Validate/clamp duration if provided
        duration = command.duration_s
        if duration is not None:
            if duration < 0:
                duration = 0.0
            if self._max_duration_s is not None and duration > self._max_duration_s:
                duration = self._max_duration_s

        # If there is an in-flight actuation, cancel it so latest command wins
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass

        if not command.value:
            # Explicit OFF command, no timing logic
            self._device.off()
            self._current_task = None
            return

        # ON command - possibly timed
        self._device.on()

        if duration is None:
            # Leave on until an explicit OFF or stop()
            self._current_task = None
            return

        async def _run_for(d: float) -> None:
            try:
                await asyncio.sleep(d)
            finally:
                self._device.off()

        self._current_task = asyncio.create_task(_run_for(duration))

    async def _aclose(self) -> None:
        # Ensure relay is off and any running task is cancelled
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
        self._device.off()
        self._device.close()