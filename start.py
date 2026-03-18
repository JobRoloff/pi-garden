import asyncio
import board

from analytics import Analytics, ActuatorEventsAdapter, DHT22Adapter, AS7341Adapter
from controllers import HumidityController
from peripherals import DHT22
from peripherals.sensors.as7341 import AS7341Module
from peripherals.manager import Manager
from peripherals.actuators.relay import Relay

from mqtt_client import MqttClient

async def main():
    mqtt_client = MqttClient(logger=print)
    if not mqtt_client.connect(timeout_s=5.0, start_loop=True):
        raise SystemExit(f"MQTT connect failed: {mqtt_client.last_error()}")

    async def publish_summary(payload: dict) -> None:
        await asyncio.to_thread(mqtt_client.publish_json, payload, topic=mqtt_client.config.topic_pub)

    async def publish_points(payload: dict) -> None:
        await asyncio.to_thread(mqtt_client.publish_json, payload, topic=mqtt_client.config.topic_pub_points)

    analytics = Analytics(mqtt_publisher=publish_summary, points_publisher=publish_points)
    await analytics.start()
    
    manager = Manager()

    humidifier_relay = Relay(name="humidifier", metric="humidity", gpio_pin=17, max_duration_s=60.0)
    humidifier_adapter = ActuatorEventsAdapter(humidifier_relay, analytics)
    manager.add_actuator(humidifier_adapter._actuator)

    humidity_controller = HumidityController(
        actuator=humidifier_relay,
        target_low_pct=55.0,
        target_high_pct=60.0,
        control_window_s=60.0,
    )

    setupDHT22(manager, analytics, humidity_controller)

    as7341 = AS7341Module(name="light")
    as7341_adapter_analytics = AS7341Adapter(analytics)
    manager.add_sensor(as7341, on_sample=as7341_adapter_analytics.on_sample)
    try:
        await manager.run_peripherals()
    finally:
        await analytics.stop()

def setupDHT22(manager: Manager, analytics, humidity_controller):
    dht22_adapter_analytics = DHT22Adapter(analytics)
    gpio_pin_4_circuit_python_notation = "D4"
    gpio_4_pin_obj = getattr(board, gpio_pin_4_circuit_python_notation, None)
    # create the sensor, specifying what gpio pin to use, the name / id, how often to run the sensor
    dht_22 = DHT22(pin_obj=gpio_4_pin_obj, name="DHT22", frequency=30.0)

    def on_dht_sample(sensor, value, ts):
        dht22_adapter_analytics.on_sample(sensor, value, ts)
        return humidity_controller.on_sample(sensor, value, ts)

    manager.add_sensor(dht_22, on_sample=on_dht_sample)

if __name__ == "__main__":
    asyncio.run(main())