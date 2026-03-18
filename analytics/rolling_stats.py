from collections import deque
from statistics import median
from typing import Deque, Optional

class RollingStats:
    """
    Per-series rolling metrics.

    Keeps:
      - a sliding window for mean/median
      - a running EWMA
    """

    def __init__(self, *, window: int, ewma_alpha: float) -> None:
        self.window = window
        self.ewma_alpha = ewma_alpha

        # Lazy per-series state
        self._windows: dict[str, Deque[float]] = {}
        self._sums: dict[str, float] = {}
        self._ewma: dict[str, Optional[float]] = {}

    def series_keys(self) -> list[str]:
        return list(self._windows.keys())

    def update(self, series: str, value: float) -> None:
        if series not in self._windows:
            self._windows[series] = deque(maxlen=self.window)
            self._sums[series] = 0.0
            self._ewma[series] = None

        w = self._windows[series]
        if len(w) == w.maxlen:
            self._sums[series] -= w[0]
        w.append(value)
        self._sums[series] += value

        prev = self._ewma[series]
        if prev is None:
            self._ewma[series] = value
        else:
            a = self.ewma_alpha
            self._ewma[series] = a * value + (1.0 - a) * prev

    def mean(self, series: str) -> Optional[float]:
        w = self._windows.get(series)
        if not w:
            return None
        return self._sums[series] / len(w)

    def median(self, series: str) -> Optional[float]:
        w = self._windows.get(series)
        if not w:
            return None
        return float(median(w))

    def ewma(self, series: str) -> Optional[float]:
        return self._ewma.get(series)