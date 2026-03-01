
## Getting Started

### GPIO Pin Setup

gpio pin 17: toggles relay
gpio pin 4: DHT-22 signal wire
gpio pin 

### Code Config

get the ip address of the computer running the otther project witht the mqttt broker ()

Create venv && install dependencies

```bash
python -m .venv venv
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
- 3.3v Humidifier Module
- 3.3v relay module