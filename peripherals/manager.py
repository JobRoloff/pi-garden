import asyncio
import time
from datetime import datetime

from typing import Any, Callable, Dict, List, Optional

from .sensors import Sensor
from .actuators import Actuator

OnSample = Callable[[Sensor, Any, float], Any]


class Manager:
    """
    Handles the scheduling of when to run each configured peripheral
    and the logic behind adding sensors to our various services.

    Callbacks are stored per sensor (keyed by sensor name) so each
    peripheral type can use its own adapter.
    """
    def __init__(self):
        self.sensors: List[Sensor] = []
        self.sensor_callbacks: Dict[str, OnSample] = {}
        self.running_tasks: List[asyncio.Task] = []
        self.keep_running = False

        # Actuators managed alongside sensors (for cleanup and future orchestration)
        self.actuators: List[Actuator] = []

    def add_sensor(self, sensor: Sensor, on_sample: Optional[OnSample] = None):
        self.sensors.append(sensor)
        if on_sample is not None:
            self.sensor_callbacks[sensor.name] = on_sample

    def add_actuator(self, actuator: Actuator) -> None:
        """
        Register an actuator with the manager so it can be tracked and
        cleaned up on shutdown. Higher-level controllers are still
        responsible for deciding when to issue commands.
        """
        self.actuators.append(actuator)

    async def _monitor_sensor_loop(self, sensor: Sensor):
        """
        Runs an infinite loop for the provided sensor arg. Upon successful reading, tthe loop waits for the sensor's defined frequency
        """
        while self.keep_running:
            try:
                val = await sensor.read()
                ts = time.time()
                s = datetime.fromtimestamp(ts).strftime("%a %b %d %I:%M %p")
                
                if val is not None:
                    on_sample = self.sensor_callbacks.get(sensor.name)
                    if on_sample is not None:
                        print("sensor loop val: ", val)
                        print("sensor loop time: ", s)
                        maybe = on_sample(sensor, val, ts)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    await asyncio.sleep(sensor.frequency)
            except asyncio.CancelledError:
                print(f"Stopping {sensor.name}...")
                break
            except Exception as e:
                print(f"Error reading {sensor.name}: {e}")
                # Sleep briefly on error to avoid rapid-fire failure loops
                await asyncio.sleep(5) 

    async def start_monitoring(self):
        """
        Spawns a separate independent loop for every sensor. No actuator quite yet..
        """
        
        # a shared flag for our each of our parallel loops to utilize to know when to stop their infite exection
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
        """
        Runs peripherals in parallel and cleans resorces when
        """
        try:
            await self.start_monitoring()
        finally:
            print("Demo finished.")
            self.stop_monitoring()
            await asyncio.gather(*self.running_tasks, return_exceptions=True)

            # Ensure actuators get a chance to release GPIO/resources
            for actuator in self.actuators:
                try:
                    await actuator.aclose()
                except Exception as e:
                    print(f"Error closing actuator {actuator.name}: {e}")

