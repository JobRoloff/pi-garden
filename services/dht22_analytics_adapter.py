from core.analytics import Analytics
from core.dht22 import DHTReading  # wherever you defined it

class DHT22AnalyticsAdapter:
    def __init__(self, analytics: Analytics):
        self.a = analytics

    def on_sample(self, sensor_name: str, value, ts: float):
        if sensor_name == "DHT22":
            # value is a DHTReading dataclass
            if isinstance(value, DHTReading):
                self.a.update_series(
                    {"temp": value.temperature_c, "humidity": value.humidity_pct},
                    now_ts=ts,
                )
            else:
                # fallback if you ever switch to tuple returns
                temp_c, humidity_pct = value
                self.a.update_series({"temp": temp_c, "humidity": humidity_pct}, now_ts=ts)