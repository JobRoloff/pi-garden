from dataclasses import dataclass

@dataclass
class HysteresisConfig:
    low: float
    high: float
    debounce_sec: float = 0.0
    min_on_sec: float = 0.0
    min_off_sec: float = 0.0