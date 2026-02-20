import asyncio
import adafruit_dht
from dataclasses import dataclass

from core.peripherals import Sensor

@dataclass(frozen=True)
class DHTReading:
    temperature_c: float
    humidity_pct: float

class DHT22(Sensor):
    def __init__(self, *,pin_obj, use_pulseio: bool = False, frequency: float = 30.0, name: str) -> None:
        super().__init__(name=name, metric="temp", frequency=frequency)
        self._sensor = adafruit_dht.DHT22(pin_obj, use_pulseio=use_pulseio)
    
    def _read_sync(self):
        temp_c = self._sensor.temperature
        hum = self._sensor.humidity
        if temp_c is None or hum is None:
            return None
        return DHTReading(temp_c, hum)
        
    async def read(self):
        try:
            return await asyncio.to_thread(self._read_sync)
        except (RuntimeError, OSError):
            return None
     