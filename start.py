import asyncio
import board

from analytics import Analytics, ActuatorEventsAdapter
from analytics.dht22_adapter import DHT22Adapter
from analytics.as7341_adapter import AS7341Adapter
from controllers import HumidityController
from peripherals import DHT22
from peripherals.sensors.as7341 import AS7341Module
from peripherals.manager import Manager
from peripherals.actuators.actuator import ActuatorCommand
from peripherals.actuators.relay import Relay

from mqtt_client import MqttClient

async def main():
    print("starting up garden system...")
    
    mqtt_client = MqttClient(logger=print)
    
    if not mqtt_client.connect(timeout_s=5.0, start_loop=True):
        raise SystemExit(f"MQTT connect failed: {mqtt_client.last_error()}")

    # async adapter: Analytics expects async Publisher(payload)->None
    async def publish_summary(payload: dict) -> None:
        print("[publish] topic:", repr(mqtt_client.cfg.topic_pub), "keys:", list(payload.keys()))
        info = await asyncio.to_thread(mqtt_client.publish_json, payload, topic=mqtt_client.cfg.topic_pub)
        print("[publish] rc:", info.rc, "mid:", info.mid)

    async def publish_points(payload: dict) -> None:
        print("[publish] topic:", repr(mqtt_client.cfg.topic_pub_points), "points:", len(payload.get("points", [])))
        info = await asyncio.to_thread(mqtt_client.publish_json, payload, topic=mqtt_client.cfg.topic_pub_points)
        print("[publish] rc:", info.rc, "mid:", info.mid)

    analytics = Analytics(mqtt_publisher=publish_summary, points_publisher=publish_points)
    await analytics.start()
    
    # dht-22 measures more than 1 thing... Use an adapter to handle a dynamic set of internal values for us to store
    dht22_adapter_analytics = DHT22Adapter(analytics)
    manager = Manager()

    # using the module provided by circuit python called board, get the object that represents gpio pin 4 (what we're hooking the dht-22's signal wire to). for some reason here its called D4..
    pin_obj = getattr(board, "D4", None)
    # create the sensor, specifying what gpio pin to use, the name / id, how often to run the sensor
    dht_22 = DHT22(pin_obj=pin_obj, name="DHT22", frequency=30.0)

    humidifier_relay = Relay(
        name="humidifier",
        metric="humidity",
        gpio_pin=17,
        max_duration_s=60.0,
    )
    humidifier_with_analytics = ActuatorEventsAdapter(humidifier_relay, analytics)
    manager.add_actuator(humidifier_with_analytics)

    humidity_controller = HumidityController(
        actuator=humidifier_with_analytics,
        target_low_pct=55.0,
        target_high_pct=60.0,
        control_window_s=60.0,
    )

    def on_dht_sample(sensor, value, ts):
        dht22_adapter_analytics.on_sample(sensor, value, ts)
        return humidity_controller.on_sample(sensor, value, ts)

    manager.add_sensor(dht_22, on_sample=on_dht_sample)

    as7341 = AS7341Module(name="light")
    as7341_adapter_analytics = AS7341Adapter(analytics)
    manager.add_sensor(as7341, on_sample=as7341_adapter_analytics.on_sample)
    try:
        await manager.run_peripherals()
    finally:
        await analytics.stop()

async def _test_async():
    relay = Relay(
        name="humidifier",
        metric="humidity",
        gpio_pin=17,
        max_duration_s=60.0,
    )
    try:
        await relay.apply(ActuatorCommand(value=True, duration_s=None, reason="test: keep on"))
        print("relay on (gpio 17); Ctrl+C to exit")
        while True:
            await asyncio.sleep(1)
    finally:
        await relay.aclose()


def test():
    print("running gpio 17")
    asyncio.run(_test_async())


if __name__ == "__main__":
    asyncio.run(main())
    # test()