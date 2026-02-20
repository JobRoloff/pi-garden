
# Raspberry Pi Garden

An ioT project to monitor a greenhouse and predict how the environment will change based on actuator activation.

## Getting Started

1. Create venv && install dependencies

```bash
python -m .venv venv
source .venv/bin/activate

pip install -r requirements.txt
```

2. (Optional if you want cloud data persistance) Populate your example.env file with the tigercloud service credentials. Rename example.env to just .env

Note if you don't go the cloud route, ensure the db related code is commented out.


3. Run the script.

```bash
python3 start.py
```

## Data Analytics

Raw Sensor data is temporarily stored on this devicee. After a certain amount of time, we calculatte the following:

- Rolling mean / median
- Ewma / exponential smoothing

The raw and computed data is then persisted into the cloud - assuming you have valid tigercloud credentials in your .env file  

## Hardware

- Pi 4b
- DHT-22
- Humidifier Module
- 3.3v relay module