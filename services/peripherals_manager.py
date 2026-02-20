import asyncio
import time

from typing import Any, List, Awaitable, Callable, List, Optional

from core.peripherals import Sensor
from core.dht22 import DHT22

import board

OnSample = Callable[[str, Any, float], Any]

class PeripheralsManager:
    """
    handles the scheduling of when to run each peripheral service
    also handles the logic behind adding actual sensors to our various services
    
    both are done in the same place because of choosing to store similar info in a single table rather than multiple
    
    """
    def __init__(self, on_sample: Optional[OnSample] = None):
        self.sensors: List[Sensor] = []
        self.running_tasks: List[asyncio.Task] = []
        self.keep_running = False
        self.on_sample = on_sample

    def add_sensor(self, sensor: Sensor):
        self.sensors.append(sensor)

    async def _monitor_sensor_loop(self, sensor: Sensor):
        """
        Internal method: Runs an infinite loop specifically for ONE sensor.
        """
        while self.keep_running:
            try:
                val = await sensor.read()
                print("sensor loop val: ", val)
                ts = time.time()
                
                if val is not None and self.on_sample is not None:
                    maybe = self.on_sample(sensor.name, val, ts)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                    await asyncio.sleep(sensor.frequency)
                    
                
                # 2. (Optional) Send to Hypertable API here
                # await self.db.save(val)
                
                
            except asyncio.CancelledError:
                print(f"Stopping {sensor.name}...")
                break
            except Exception as e:
                print(f"Error reading {sensor.name}: {e}")
                # Sleep briefly on error to avoid rapid-fire failure loops
                await asyncio.sleep(5) 

    async def start_monitoring(self):
        """
        Spawns a separate independent loop for every sensor.
        """
        self.keep_running = True
        print("Starting all sensor loops...")
        
        for sensor in self.sensors:
            # Create a background task for this sensor's loop
            task = asyncio.create_task(self._monitor_sensor_loop(sensor))
            self.running_tasks.append(task)
            
        # We now have multiple loops running in parallel.
        # We need to keep the main program alive to let them run.
        try:
            # Wait until someone cancels the tasks (or runs forever)
            await asyncio.gather(*self.running_tasks)
        except asyncio.CancelledError:
            pass

    def stop_monitoring(self):
        self.keep_running = False
        for task in self.running_tasks:
            task.cancel()

    async def run_peripherals(self):
        try:
            await self.start_monitoring()
        finally:
            print("Demo finished.")
            self.stop_monitoring()
            await asyncio.gather(*self.running_tasks, return_exceptions=True)

async def main():
    pin = "D4"
    pin_obj=getattr(board, pin, None)
    
    s1 = DHT22(pin_obj=pin_obj,name="DHT22", frequency=30.0)
    
    mgr = PeripheralsManager()
    mgr.add_sensor(s1)

    await mgr.run_peripherals()

if __name__ == "__main__":
    print("running peripherals manager directly")
    asyncio.run(main())