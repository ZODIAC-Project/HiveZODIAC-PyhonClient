#!/usr/bin/env python3
"""Simple loop publisher that periodically sends ingest messages.
This re-uses the existing `client_publisher.py` code in the repo.
Environment variables control broker/identity/topic.
"""
import os
import time
import json
import logging

from poc.client_publisher import Publisher

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("poc.loop_publisher")

BROKER = os.environ.get("BROKER_HOST", "localhost")
PORT = int(os.environ.get("BROKER_PORT", 1883))
CLIENT_ID = os.environ.get("CLIENT_ID", "publisher1")
TOPIC = os.environ.get("TOPIC", "db/ingest/device/device-1")
USER = os.environ.get("USER", "device-1")
PURPOSE = os.environ.get("PURPOSE", "ingest")
INTERVAL = float(os.environ.get("INTERVAL", 5))

if __name__ == "__main__":
    p = Publisher(BROKER, PORT, client_id=CLIENT_ID)
    p.connect()
    count = 0
    while True:
        payload = {"value": count}
        LOG.info("Publishing sample payload %s to %s", payload, TOPIC)
        try:
            p.send_message(TOPIC, USER, PURPOSE, payload)
        except Exception:
            LOG.exception("Failed to publish message")
        count += 1
        time.sleep(INTERVAL)
