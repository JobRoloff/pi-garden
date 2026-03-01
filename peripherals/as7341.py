import board
import asyncio
from time import sleep
from adafruit_as7341 import AS7341
from dataclasses import dataclass

from .sensor import Sensor

@dataclass(frozen=True)
class AS7341Reading:
    violet_451 : int
    indigo_445: int
    blue_480: int
    cyan_515: int
    green_555: int
    yellow_590: int
    orange_630: int
    red_680: int
    clear: int
    near_ir: int   

class AS7341Module(Sensor):
    def __init__(self, *, frequency: float = 30.0, name: str) -> None:
        super().__init__(name=name, metric="light", frequency=frequency)
        i2c = board.I2C()
        self._sensor = AS7341(i2c)
    
    def _read_sync(self):
        violet_451  = self._sensor.channel_415nm
        indigo_445 = self._sensor.channel_445nm
        blue_480 = self._sensor.channel_480nm
        cyan_515 = self._sensor.channel_515nm
        green_555 = self._sensor.channel_555nm
        yellow_590 = self._sensor.channel_590nm
        orange_630 = self._sensor.channel_630nm
        red_680 = self._sensor.channel_680nm
        clear = self._sensor.channel_clear
        near_ir = self._sensor.channel_nir

        return AS7341Reading(violet_451, indigo_445, blue_480, cyan_515, green_555, yellow_590, orange_630, red_680, clear, near_ir)
        
    async def read(self):
        try:
            return await asyncio.to_thread(self._read_sync)
        except (RuntimeError, OSError):
            return None

def main():
    i2c = board.I2C()  # uses board.SCL and board.SDA
    sensor = AS7341(i2c)


    def bar_graph(read_value):
        scaled = int(read_value / 1000)
        return "[%5d] " % read_value + (scaled * "*")


    while True:
        print("F1 - 415nm/Violet  %s" % bar_graph(sensor.channel_415nm))
        print("F2 - 445nm//Indigo %s" % bar_graph(sensor.channel_445nm))
        print("F3 - 480nm//Blue   %s" % bar_graph(sensor.channel_480nm))
        print("F4 - 515nm//Cyan   %s" % bar_graph(sensor.channel_515nm))
        print("F5 - 555nm/Green   %s" % bar_graph(sensor.channel_555nm))
        print("F6 - 590nm/Yellow  %s" % bar_graph(sensor.channel_590nm))
        print("F7 - 630nm/Orange  %s" % bar_graph(sensor.channel_630nm))
        print("F8 - 680nm/Red     %s" % bar_graph(sensor.channel_680nm))
        print("Clear              %s" % bar_graph(sensor.channel_clear))
        print("Near-IR (NIR)      %s" % bar_graph(sensor.channel_nir))
        print("\n------------------------------------------------")
        sleep(1)

async def test():
    sensor = AS7341Module(name="sun-bob")
    return await sensor.read()

if __name__ == "__main__":
    print("running as7341 directly")
    # test using direct sensor library calls
    # main()
    # test using the class
    # v = asyncio.run(test())
    # print(v)