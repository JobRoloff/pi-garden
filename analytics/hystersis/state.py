from dataclasses import dataclass
from typing import Optional

@dataclass
class HysteresisState:
    is_on: bool = False
    last_change_ts: float = 0.0
    pending_switch: Optional[bool] = None
    pending_since_ts: float = 0.0