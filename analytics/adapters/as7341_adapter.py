from ..analytics import Analytics
from peripherals import Sensor 
from peripherals.sensors.as7341 import AS7341Module, AS7341Reading

class AS7341Adapter:
    """
    AST7341 reads 10 ints. This clas formats the int values into a series which we could then use in our data ingestion pipeline
    """
    def __init__(self, analytics: Analytics):
        self.a = analytics
    
    def on_sample(self, sensor: Sensor, value, ts: float):
        if not isinstance(sensor, AS7341Module):
            return
        
        if isinstance(value, AS7341Reading):
            self.a.ingest_series(
                {
                    "indigo_445": value.indigo_445,
                    "violet_451": value.violet_451,
                    "blue_480": value.blue_480,
                    "cyan_515": value.cyan_515,
                    "green_555": value.green_555,
                    "yellow_590": value.yellow_590,
                    "orange_630": value.orange_630,
                    "red_680": value.red_680,
                    "clear": value.clear,
                    "near_ir": value.near_ir,
                },
                now_ts=ts,
                sensor_id=sensor.name,
                sensor_type=type(sensor).__name__,
            )
