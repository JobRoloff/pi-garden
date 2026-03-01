import asyncio
import board

from analytics import Analytics
from analytics.dht22_adapter import DHT22Adapter
from analytics.as7341_adapter import AS7341Adapter
from peripherals.dht22 import DHT22
from peripherals.as7341 import AS7341Module
from peripherals.manager import Manager

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
    manager.add_sensor(dht_22, on_sample=dht22_adapter_analytics.on_sample)

    as7341 = AS7341Module(name="light")
    as7341_adapter_analytics = AS7341Adapter(analytics)
    manager.add_sensor(as7341, on_sample=as7341_adapter_analytics.on_sample)
    try:
        await manager.run_peripherals()
    finally:
        await analytics.stop()

    
if __name__ == "__main__":
    asyncio.run(main())