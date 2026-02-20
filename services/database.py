from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union, LiteralString
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

JSONLike = Union[Dict[str, Any], List[Any], str, int, float, bool, None]


@dataclass(frozen=True)
class SensorReading:
    """Convenience type for passing readings around in code."""
    device_name: str
    time: datetime
    metric: str
    value: float


Params = Optional[Union[Tuple[Any, ...], Dict[str, Any]]]


def _ensure_conninfo_params(conninfo: str) -> str:
    """
    Ensure required/safer params exist in the connection string:
    - sslmode=require (common requirement for managed Timescale/Tiger Cloud)
    - connect_timeout=10 (fail fast)
    """
    # If it's not a URL, just return as-is (psycopg also accepts keyword-style strings)
    if "://" not in conninfo:
        # try to be helpful anyway
        if "sslmode=" not in conninfo:
            conninfo += " sslmode=require"
        if "connect_timeout=" not in conninfo:
            conninfo += " connect_timeout=10"
        return conninfo

    u = urlparse(conninfo)
    q = dict(parse_qsl(u.query, keep_blank_values=True))

    q.setdefault("sslmode", "require")
    q.setdefault("connect_timeout", "10")

    return urlunparse(
        (u.scheme, u.netloc, u.path, u.params, urlencode(q), u.fragment)
    )


class Database:
    """
    Singleton DB client.
    """

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "Database":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_once()
        return cls._instance

    def _init_once(self) -> None:
        load_dotenv()
        connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
        if not connection_string:
            raise RuntimeError(
                "POSTGRES_CONNECTION_STRING is missing. Add it to your .env or export it."
            )

        connection_string = _ensure_conninfo_params(connection_string)

        # Create pool
        self._pool = ConnectionPool(
            conninfo=connection_string,
            min_size=1,
            max_size=10,
            timeout=10,
        )

        # Open eagerly so connection problems surface immediately
        try:
            self._pool.open(wait=True, timeout=10)
            self.ensure_schema()
        except Exception as e:
            raise RuntimeError(
                "Failed to open DB connection pool. "
                "Common causes: wrong host/port, missing sslmode=require, "
                "blocked network, bad credentials, or password needs URL-encoding. "
                f"Original error: {e}"
            ) from e

    # helpers
    def execute(self, sql: LiteralString, params: Params = None) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()

    def fetchone(self, sql: LiteralString, params: Params = None) -> Optional[Tuple[Any, ...]]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()

    def fetchall(self, sql: LiteralString, params: Params = None) -> List[Tuple[Any, ...]]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    # ---------- time-series logging ----------

    def ensure_schema(self) -> None:
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
              time         TIMESTAMPTZ NOT NULL,
              device_name  TEXT        NOT NULL,
              metric       TEXT        NOT NULL,
              value        DOUBLE PRECISION NOT NULL
            );
            """
        )

        self.execute("CREATE INDEX IF NOT EXISTS idx_logs_time ON logs (time DESC);")
        self.execute(
            "CREATE INDEX IF NOT EXISTS idx_logs_device_metric_time ON logs (device_name, metric, time DESC);"
        )

    def log(
        self,
        *,
        device_name: str,
        metric: str,
        value: float,
        time: Optional[datetime] = None,
    ) -> None:
        ts = time or datetime.now(timezone.utc)
        self.execute(
            """
            INSERT INTO logs (time, device_name, metric, value)
            VALUES (%s, %s, %s, %s);
            """,
            (ts, device_name, metric, value),
        )

    def log_many(self, readings: Sequence[SensorReading]) -> None:
        if not readings:
            return

        rows = [(r.time, r.device_name, r.metric, r.value) for r in readings]

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO logs (time, device_name, metric, value)
                    VALUES (%s, %s, %s, %s);
                    """,
                    rows,
                )
            conn.commit()

    def close(self) -> None:
        self._pool.close()
