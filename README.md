# Raspberry Pi Garden Automation

A project that controlls a greenhouse environment using sensors and motors.

Data on sensor and motor usage is sent to an mqtt broker topic.

See this [dockerized mqtt broker project](https://github.com/JobRoloff/PI-Garden-Data) that could be used right out of the box with this repo.

## Getting Started

### System Dependencies

In order to use the camera, you gotta manually install the following

```bash
sydo apt update
sudo apt install -y libcamera-apps python3-picamera2 libcap-dev
```

### GPIO Pin Setup

gpio pin 17: toggles humidifier relay
gpio pin 4: DHT-22 signal wire

### Code Config

Set `MQTT_HOST` in `.env` to the IP of the machine running the MQTT broker (e.g. `192.168.1.27` for the dockerized broker).

Create venv && install dependencies

```bash
# note the system site packages are there for if you're using the camera module as well. This flass gives the venv access to system site-packages
python -m venv .venv --system-site-packages
source .venv/bin/activate

pip install -r requirements.txt
```

Run the script

```bash
python3 start.py
```

## Data Analysis Techniques

Raw Sensor and Actuator data is temporarily stored on this devicee. After a certain amount of time, we calculatte the following:

- Rolling mean / median
- Ewma / exponential smoothing

## Hardware

- Pi 4b
- DHT-22
- AS73141 10 channel light sensor
- Arducam OwlSight Camera Module
- 3.3v Humidifier Module
- 3.3v relay module

## Project Image(s)

![Garden Setup 3-3-26](./assets/pi-garden.png)