from analytics import Analytics
from peripherals.sensor import Sensor
from peripherals.dht22 import DHT22, DHTReading

class DHT22Adapter:
    """DHT22 reads two floats. This class formats the floats into a series which we could then use in our data ingestion pipeline"""
    def __init__(self, analytics: Analytics):
        self.a = analytics

    def on_sample(self,sensor: Sensor, value, ts: float):
        """
        a callback function thats passed to the manager class to then execute this callback whenever the dht22 collects data
        """
        if not isinstance(sensor, DHT22):
            return

        if isinstance(value, DHTReading):
            self.a.ingest_series(
                {"temp": value.temperature_c, "humidity": value.humidity_pct},
                now_ts=ts,
            )
        else:
            # fallback if you ever switch to tuple returns
            temp_c, humidity_pct = value
            self.a.ingest_series({"temp": temp_c, "humidity": humidity_pct}, now_ts=ts)