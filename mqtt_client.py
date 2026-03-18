import os
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

import paho.mqtt.client as mqtt

from dotenv import load_dotenv


@dataclass
class MqttConfig:
    host: str
    port: int
    topic_pub: str
    topic_pub_points: Optional[str] = None  # raw data points; default topic_pub + "/points"
    topic_sub: Optional[str] = None
    client_id: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    keepalive: int = 60
    qos: int = 1
    retain: bool = False
    tls: bool = False  # basic toggle; see notes below


def _getenv_int(key: str, default: int) -> int:
    val = os.getenv(key)
    return int(val) if val and val.strip() else default


def _getenv_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


class MqttClient:
    """
    Small wrapper around paho-mqtt for publish/subscribe with:
    - config from .env
    - background network loop
    - auto reconnect
    - simple publish_json() helper
    """

    def __init__(
        self,
        on_message: Optional[Callable[[str, bytes], None]] = None,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self._log = logger or (lambda msg: None)
        load_dotenv()
        self.config = self._config_from_env()
        self._user_on_message = on_message

        # Use v2 callback API when available; fall back gracefully.
        try:
            self._client = mqtt.Client(
                client_id="",
            )
            self._cb_v2 = True
        except Exception:
            self._client = mqtt.Client(client_id="")
            self._cb_v2 = False

        # Paho callbacks
        self._client.on_connect = self._on_connect_v2
        self._client.on_disconnect = self._on_disconnect_v2
        self._client.on_message = self._on_message_v2


        # Reconnect behavior
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        self._connected = threading.Event()
        self._stopping = False
        self._last_connect_err: Optional[str] = None

    def _config_from_env(self) -> MqttConfig:
        host = os.getenv("MQTT_HOST", "localhost")
        port = _getenv_int("MQTT_PORT", 1883)
        topic_pub = os.getenv("MQTT_TOPIC_PUB")
        if not topic_pub:
            raise ValueError("MQTT_TOPIC_PUB is empty. Set it to a real topic, e.g. pi-garden/telemetry")
        topic_pub_points = os.getenv("MQTT_TOPIC_PUB_POINTS") or f"{topic_pub.rstrip('/')}/points"
        topic_sub = os.getenv("MQTT_TOPIC_SUB")
        client_id = os.getenv("MQTT_CLIENT_ID")
        username = os.getenv("MQTT_USERNAME")
        password = os.getenv("MQTT_PASSWORD")
        keepalive = _getenv_int("MQTT_KEEPALIVE", 60)
        qos = _getenv_int("MQTT_QOS", 1)
        retain = _getenv_bool("MQTT_RETAIN", False)
        tls = _getenv_bool("MQTT_TLS", False)

        return MqttConfig(
            host=host,
            port=port,
            topic_pub=topic_pub,
            topic_pub_points=topic_pub_points,
            topic_sub=topic_sub,
            client_id=client_id,
            username=username,
            password=password,
            keepalive=keepalive,
            qos=qos,
            retain=retain,
            tls=tls,
        )

    # ---------- Public API ----------

    def connect(self, timeout_s: float = 5.0, start_loop: bool = True) -> bool:
        """
        Connect to broker and optionally start background loop thread.
        Returns True if connected within timeout.
        """
        self._stopping = False
        self._connected.clear()
        self._last_connect_err = None

        try:
            self._client.connect(self.config.host, self.config.port, keepalive=self.config.keepalive)
        except Exception as e:
            self._last_connect_err = str(e)
            self._log(f"[mqtt] connect() failed: {e}")
            return False

        if start_loop:
            self._client.loop_start()

        return self._connected.wait(timeout_s)

    def disconnect(self) -> None:
        self._stopping = True
        try:
            self._client.disconnect()
        finally:
            # Stop loop regardless; safe even if not started.
            try:
                self._client.loop_stop()
            except Exception:
                pass
            self._connected.clear()

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def last_error(self) -> Optional[str]:
        return self._last_connect_err

    def publish(
        self,
        payload: Union[str, bytes],
        topic: Optional[str] = None,
        qos: Optional[int] = None,
        retain: Optional[bool] = None,
    ) -> mqtt.MQTTMessageInfo:
        """
        Publish raw str/bytes.
        Raises RuntimeError if not connected.
        """
        if not self.is_connected():
            raise RuntimeError("MQTT client is not connected")

        t = topic or self.config.topic_pub
        q = self.config.qos if qos is None else qos
        r = self.config.retain if retain is None else retain

        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        info = self._client.publish(t, payload=payload, qos=q, retain=r)
        return info

    def publish_json(
        self,
        obj: Any,
        topic: Optional[str] = None,
        qos: Optional[int] = None,
        retain: Optional[bool] = None,
    ) -> mqtt.MQTTMessageInfo:
        """
        Publish JSON-encoded payload (utf-8).
        """
        return self.publish(
            payload=json.dumps(obj, separators=(",", ":"), ensure_ascii=False),
            topic=topic,
            qos=qos,
            retain=retain,
        )

    # ---------- Callbacks (v2 and v1) ----------

    # V2 signatures (paho-mqtt >= 2.x)
    def _on_connect_v2(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self._log(f"[mqtt] connected to {self.config.host}:{self.config.port}")
            self._connected.set()
            # Auto-subscribe if configured
            if self.config.topic_sub:
                client.subscribe(self.config.topic_sub, self.config.qos)
        else:
            self._last_connect_err = f"connect reason_code={reason_code}"
            self._log(f"[mqtt] connect failed: {self._last_connect_err}")

    def _on_disconnect_v2(self, client, userdata, reason_code, properties=None):
        self._connected.clear()
        if self._stopping:
            self._log("[mqtt] disconnected (requested)")
            return
        self._log(f"[mqtt] disconnected (reason_code={reason_code}); will auto-reconnect")

    def _on_message_v2(self, client, userdata, msg: mqtt.MQTTMessage):
        if self._user_on_message:
            self._user_on_message(msg.topic, msg.payload)