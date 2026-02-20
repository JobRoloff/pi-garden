"""
main.py is used for one off instantiation of various services. this isn't the actual long running loop where we're messing around with the physical hardware
"""
import sys
import time

from services.humidity.humidifier import HumidifierService
from services.air import AirService
from services.database import Database

def main(module_to_run):
    # db = Database()
    
    if (module_to_run == "air"):
        service = AirService(pin="D4")
        # create variables for logging. this should be done through a logging manager class. or maybe something akin to a logging manager
        device_name = "air"
        
        got_valid_reading = None
        try:
            while got_valid_reading is None:
                r = service.read()
                if r:
                    print(f"{r.temperature_c:.1f}°C / {r.temperature_f:.1f}°F  |  {r.humidity:.1f}%")
                    # db.log(device_name=device_name, metric="temperature", value = r.temperature_f)
                    # db.log(device_name=device_name, metric="humidity", value = r.humidity)
                    break
                time.sleep(2)
        finally:
            service.close()
    if (module_to_run == "humidity"):
        module = HumidifierService()
        module.run()
    

# client (you or an agent) runs in the cli:  python3 main.py humidify
if  __name__ == "__main__":
    module_to_run = sys.argv[1]
    main(module_to_run)