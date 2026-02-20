import asyncio
import board

from core.analytics import Analytics
from core.dht22 import DHT22
from services.peripherals_manager import PeripheralsManager
from services.dht22_analytics_adapter import DHT22AnalyticsAdapter

async def main():
    print("starting up garden system...")
    
    analytics = Analytics(dt_sec=30.0)
    adapter = DHT22AnalyticsAdapter(analytics)
    
    manager = PeripheralsManager(on_sample=adapter.on_sample)

    pin_obj=getattr(board, "D4", None)
    dht_22 = DHT22(pin_obj=pin_obj,name="DHT22", frequency=30.0)
    
    manager.add_sensor(dht_22)
    await manager.run_peripherals()

    
if __name__ == "__main__":
    asyncio.run(main())