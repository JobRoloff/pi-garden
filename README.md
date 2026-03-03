
## Getting Started

### System Dependencies

In order to use the camera, you gotta manually install the following

```bash
sydo apt update
sudo apt install -y libcamera-apps python3-picamera2
```

### GPIO Pin Setup

gpio pin 17: toggles relay
gpio pin 4: DHT-22 signal wire
gpio pin 

### Code Config

get the ip address of the computer running the otther project witht the mqttt broker ()

Create venv && install dependencies

```bash
# note the system site packages are there for if you're using the camera module as well. This flass gives the venv access to system site-packages
python -m .venv venv --system-site-packages
source .venv/bin/activate

pip install -r requirements.txt
```

Run the script

```bash
python3 start.py
```



## Data Analysis Techniques

Raw Sensor data is temporarily stored on this devicee. After a certain amount of time, we calculatte the following:

- Rolling mean / median
- Ewma / exponential smoothing

The raw and computed data is then persisted into the cloud - assuming you have valid tigercloud credentials in your .env file  

## Hardware

- Pi 4b
- DHT-22
- AS73141 10 channel light sensor
- Arducam OwlSight Camera Module
- 3.3v Humidifier Module
- 3.3v relay module