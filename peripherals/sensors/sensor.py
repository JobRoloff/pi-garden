from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Generic, TypeVar

T = TypeVar("T")
V = TypeVar("V")

class Sensor(ABC, Generic[T, V]):
    def __init__(self, name: str, metric: V, frequency: float = 30.0):
        self.name = name
        self.metric: V = metric
        self.frequency = frequency
        self.value: Optional[T] = None

        self._closed = False

    @abstractmethod
    async def read(self) -> Optional[T]:
        """Read a sample from the sensor. Return None on failure/no sample."""
        raise NotImplementedError

    # ---- Subclass hooks (override one or both) ----
    def _close(self) -> None:
        """Sync cleanup hook for subclasses (GPIO release, file close, etc.)."""
        return None

    async def _aclose(self) -> None:
        """Async cleanup hook for subclasses.

        Default: run _close() in the event loop thread.
        Override if you have true async cleanup.
        """
        self._close()

    # ---- Public close API ----
    def close(self) -> None:
        """Synchronous close.

        If you used async resources and didn't override _close(), prefer aclose().
        """
        if self._closed:
            return
        self._closed = True
        self._close()

    async def aclose(self) -> None:
        """Asynchronous close (preferred in async apps)."""
        if self._closed:
            return
        self._closed = True
        await self._aclose()

    # ---- Context manager support ----
    def __enter__(self) -> "Sensor[T, V]":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()  # don't swallow exceptions from the with-body

    async def __aenter__(self) -> "Sensor[T, V]":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()