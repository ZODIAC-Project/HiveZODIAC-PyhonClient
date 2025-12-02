"""
script to send reservation control messages.
"""
import argparse
import json
import logging
import uuid
import threading
import time
import paho.mqtt.client as mqtt

LOG = logging.getLogger("poc.reserve")
logging.basicConfig(level=logging.INFO)


def publish_msg(broker, port, payload):
    cli = mqtt.Client(client_id=f"poc-reserve-{uuid.uuid4()}")
    connected = threading.Event()

    def _on_connect(client, userdata, flags, rc):
        connected.set()

    cli.on_connect = _on_connect
    try:
        cli.connect(broker, port)
        cli.loop_start()
        # wait for connect up to 3s so publish has a chance to be delivered
        if not connected.wait(timeout=3):
            LOG.warning("MQTT connect did not complete within timeout; publish may fail")
        # Use QoS=1 so the broker sends a PUBACK — more reliable delivery.
        info = cli.publish("control/reservations", payload, qos=1)
        # wait for publish to complete in a version-compatible way
        timeout = 10.0
        start = time.time()
        try:
            while not info.is_published():
                if time.time() - start > timeout:
                    LOG.warning("Reservation publish did not complete within timeout")
                    break
                time.sleep(0.1)
            else:
                LOG.info("Reservation publish completed (PUBACK received)")
        except Exception as e:
            LOG.warning("Exception while waiting for reservation publish: %s", e)
    finally:
        try:
            cli.loop_stop()
        except Exception:
            pass
        try:
            cli.disconnect()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    r = sub.add_parser("reserve")
    r.add_argument("--topic", required=True)
    r.add_argument("--pip", default=None)
    r.add_argument("--aip", default=None)
    r2 = sub.add_parser("unreserve")
    r2.add_argument("--topic", required=True)
    s = sub.add_parser("set-allow")
    s.add_argument("--value", type=int, choices=[0, 1], default=1)
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    payload = None
    if args.cmd == "reserve":
        pip = args.pip.split(",") if args.pip else []
        aip = args.aip.split(",") if args.aip else []
        payload = json.dumps({"action": "reserve", "topic": args.topic, "pip": pip, "aip": aip})
    elif args.cmd == "unreserve":
        payload = json.dumps({"action": "unreserve", "topic": args.topic})
    elif args.cmd == "set-allow":
        payload = json.dumps({"action": "set-allow-without-res", "value": bool(args.value)})
    else:
        parser.print_help()
        return
    LOG.info("Publishing reservation payload: %s", payload)
    publish_msg(args.broker, args.port, payload)


if __name__ == "__main__":
    main()
