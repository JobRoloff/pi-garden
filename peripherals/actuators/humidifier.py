from gpiozero import DigitalOutputDevice
from time import sleep
from .actuator import Actuator

class Humidifier(Actuator):
    def __init__():
        return
    
    def test(self): 
        print("test")
    def run(self):
        print("running humidifier")
        # Use the number printed as GPIOxx on your T-Cobbler (NOT 3V3 / 5V / GND).
        GPIO_PIN = 17

        # active_high=True means "on" = 3.3V on that GPIO
        pin = DigitalOutputDevice(GPIO_PIN, active_high=True, initial_value=False)

        count = 0
        try:
            while count < 3:
                pin.on()
                sleep(5)
                pin.off()
                sleep(1)
                count += 1
        except KeyboardInterrupt:
            pin.off()
            print("\nStopped.")
