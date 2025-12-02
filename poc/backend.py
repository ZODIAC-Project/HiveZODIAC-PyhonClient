"""
PoC backend that enforces MQTT topic reservations and writes accepted messages to SQLite.

Usage:
  python poc/backend.py --broker localhost --port 1883

This backend listens to two MQTT topics:
 - control/reservations: receive JSON control messages to set/unset reservations
 - db/ingest/#: receive JSON ingestion messages from clients

The backend enforces topic reservations. If a reservation allows the topic backend persists the message and publishes an ack.
"""
import os
import argparse
import json
import logging
import re
import sqlite3
import uuid
from typing import Dict, Any, List

import paho.mqtt.client as mqtt

LOG = logging.getLogger("poc.backend")
logging.basicConfig(level=logging.INFO)


def topic_to_regex(pattern: str) -> str:
    # Convert MQTT topic pattern to regex; support + and #
    # Escape regex chars and replace + with [^/]+ and # with .* (end)
    pat = re.escape(pattern)
    pat = pat.replace(r"\+", "[^/]+")
    pat = pat.replace(r"\#", ".*")
    # Ensure full match
    return r"^" + pat + r"$"


class Reservation:
    def __init__(self, topic: str, aip: List[str] = None, pip: List[str] = None):
        self.topic = topic
        self.aip = aip or []
        self.pip = pip or []
        self._regex = re.compile(topic_to_regex(topic))

    def matches(self, topic: str) -> bool:
        return bool(self._regex.match(topic))

    def __repr__(self):
        return f"Reservation(topic={self.topic}, aip={self.aip}, pip={self.pip})"


class POCBackend:
    def __init__(self, broker: str, port: int = 1883, dbfile: str = "poc.db", username: str = None, password: str = None, allow_without_reservation: bool = True):
        self.broker = broker
        self.port = int(port)
        self.conn = sqlite3.connect(dbfile, check_same_thread=False)
        self._setup_db()

        self.reservations: Dict[str, Reservation] = {}
        self.allow_without_reservation = bool(allow_without_reservation)

        self.client = mqtt.Client(client_id=f"poc-backend-{uuid.uuid4()}")
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _setup_db(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS records (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user TEXT,
               topic TEXT,
               payload TEXT,
               ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def _on_connect(self, client, userdata, flags, rc):
        LOG.info("Connected to MQTT broker %s:%s rc=%s", self.broker, self.port, rc)
        # Subscribe to reservation control and ingest topics
        client.subscribe("control/reservations")
        client.subscribe("db/ingest/#")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        LOG.debug("Message on %s: %s", topic, payload)
        if topic == "control/reservations":
            self._handle_reservation_control(payload)
            return

        if topic.startswith("db/ingest/"):
            self._handle_ingest(topic, payload)
            return

        LOG.warning("Unhandled topic %s", topic)

    def _handle_reservation_control(self, payload: str):
        try:
            data = json.loads(payload)
        except Exception as e:
            LOG.error("Invalid JSON in reservation control: %s", e)
            return
        action = data.get("action")
        topic = data.get("topic")
        if action == "reserve":
            aip = data.get("aip", [])
            pip = data.get("pip", [])
            res = Reservation(topic, aip=aip, pip=pip)
            self.reservations[topic] = res
            LOG.info("Added reservation: %s", res)
        elif action == "unreserve":
            if topic in self.reservations:
                del self.reservations[topic]
                LOG.info("Removed reservation for topic %s", topic)
        elif action == "clear":
            self.reservations.clear()
            LOG.info("Cleared all reservations")
        elif action == "set-allow-without-res":
            self.allow_without_reservation = bool(data.get("value", False))
            LOG.info("Set allow_without_reservation=%s", self.allow_without_reservation)
        else:
            LOG.warning("Unknown reservation action: %s", action)

    def _find_reservation(self, topic: str):
        matches = [r for r in self.reservations.values() if r.matches(topic)]
        if not matches:
            return None
        matches.sort(key=lambda r: len(r.topic), reverse=True)
        return matches[0]

    def _handle_ingest(self, topic: str, payload: str):
        try:
            data = json.loads(payload)
        except Exception:
            LOG.exception("Invalid JSON payload on topic %s", topic)
            return
        client_id = data.get("client_id")
        msg_id = data.get("msg_id")
        user = data.get("user")
        if user is None:
            self._publish_ack(client_id, msg_id, False, "missing user")
            return
        # Check reservation presence (topic-level). If there is no matching
        # reservation and strict mode is enabled, reject.
        res = self._find_reservation(topic)
        if res is None and not self.allow_without_reservation:
            LOG.info("No reservation for %s and strict mode, rejecting", topic)
            self._publish_ack(client_id, msg_id, False, "no reservation for topic")
            return

        # Accept and persist to DB
        LOG.info("Storing message from %s on %s", user, topic)
        c = self.conn.cursor()
        c.execute("INSERT INTO records (user, topic, payload) VALUES (?, ?, ?)", (user, topic, json.dumps(data.get("data"))))
        self.conn.commit()
        self._publish_ack(client_id, msg_id, True, "ok")

    def _publish_ack(self, client_id: str, msg_id: str, accepted: bool, reason: str):
        if not client_id:
            LOG.debug("No client_id in message, skipping ack")
            return
        topic = f"db/ack/{client_id}/{msg_id}"
        payload = json.dumps({"accepted": accepted, "reason": reason})
        self.client.publish(topic, payload, qos=1)

    def run(self):
        self.client.connect(self.broker, self.port)
        self.client.loop_forever()


def main():
    # Configuration via environment variables (preferred for containers/k8s)
    # BROKER_HOST: MQTT broker host (default: localhost)
    # BROKER_PORT: MQTT broker port (default: 1883)
    # DB_PATH: path to sqlite database file (default: poc.db)
    # MQTT_USER / MQTT_PASSWORD: optional MQTT credentials
    # ALLOW_WITHOUT_RESERVATION: 'true'|'false' (default: true)
    broker = os.getenv("BROKER_HOST", os.getenv("BROKER", "localhost"))
    port = int(os.getenv("BROKER_PORT", os.getenv("PORT", "1883")))
    dbpath = os.getenv("DB_PATH", "poc.db")
    username = os.getenv("MQTT_USER")
    password = os.getenv("MQTT_PASSWORD")
    allow_without_res = os.getenv("ALLOW_WITHOUT_RESERVATION", "true").lower() in ("1", "true", "yes", "on")

    backend = POCBackend(broker, port, dbpath, username, password, allow_without_reservation=allow_without_res)
    backend.run()


if __name__ == "__main__":
    main()
