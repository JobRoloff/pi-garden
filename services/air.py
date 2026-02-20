from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import board

from core.dht22 import DHT22


class AirService:
    """
    Air service for reading temperature/humidity from a DHT22 sensor.

    - `pin` is a `board` pin name like "D4", "D17", etc. (BCM numbering style)
    - DHT22 reads can fail occasionally; returning None is expected sometimes.
    """

    def __init__(self, *, pin: str = "D4") -> None:
        self.pin_obj = getattr(board, pin, None)
        if self.pin_obj is None:
            raise ValueError(f"Unknown pin '{pin}'. Use names like 'D4', 'D17', 'D22'.")
        self._sensor = DHT22(name="DHT-22",pin_obj=self.pin_obj)
     

    def read(self):
        return self._sensor.read()

