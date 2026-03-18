import os
from typing import Optional

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

def _round2(x: Optional[float]) -> Optional[float]:
    """Round to 2 decimal places for payload readability."""
    return round(x, 2) if x is not None else None

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