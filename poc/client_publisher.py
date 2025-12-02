#!/usr/bin/env python3
"""
Simple publisher client that sends ingestion messages to MQTT and waits for acknowledgment.
"""
import argparse
import json
import logging
import uuid
import time
import threading

import paho.mqtt.client as mqtt

LOG = logging.getLogger("poc.publisher")
logging.basicConfig(level=logging.INFO)


class Publisher:
    def __init__(self, broker: str, port: int, client_id: str, wait_ack=True):
        self.client_id = client_id
        self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.broker = broker
        self.port = port
        self.wait_ack = wait_ack
        self._ack_event = threading.Event()
        self._last_ack = None

    def _on_connect(self, client, userdata, flags, rc):
        LOG.info("connected: rc=%s", rc)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        LOG.info("Ack received on %s: %s", topic, payload)
        self._last_ack = payload
        self._ack_event.set()

    def connect(self):
        self.client.connect(self.broker, self.port)
        # ack topic wildcard
        self.client.subscribe(f"db/ack/{self.client_id}/#")
        self.client.loop_start()

    def send_message(self, topic, user, purpose, data):
        msg_id = str(uuid.uuid4())
        payload = json.dumps({
            "client_id": self.client_id,
            "msg_id": msg_id,
            "user": user,
            "purpose": purpose,
            "data": data,
        })
        LOG.info("Publishing to %s: %s", topic, payload)
        self._ack_event.clear()
        self.client.publish(topic, payload)
        if self.wait_ack:
            ok = self._ack_event.wait(timeout=3)
            if not ok:
                LOG.warning("No ack received for msg %s", msg_id)
                return False
            else:
                LOG.info("Ack: %s", self._last_ack)
                return True
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--client-id", default="client1")
    parser.add_argument("--user", default="user-123")
    parser.add_argument("--topic", default="db/ingest/user/user-123")
    parser.add_argument("--purpose", default="ingest")
    parser.add_argument("--data", default="{\"value\": 123}")
    args = parser.parse_args()
    pub = Publisher(args.broker, args.port, client_id=args.client_id)
    pub.connect()
    time.sleep(0.2)
    pub.send_message(args.topic, args.user, args.purpose, json.loads(args.data))
    time.sleep(0.5)


if __name__ == "__main__":
    main()
