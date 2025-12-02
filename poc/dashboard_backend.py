#!/usr/bin/env python3
"""
Dashboard backend for reservations and logs.

This small API serves frontend files and provides REST + WebSocket endpoints to show
and manage reservations. It connects to the MQTT broker and subscribes to
`control/reservations` and `db/ack/#` messages.

Run:
  pip install fastapi uvicorn paho-mqtt
  python poc/dashboard_backend.py --broker localhost --port 1883 --host 0.0.0.0 --port-http 8000

This is a PoC: no auth, no persistence.
"""
import argparse
import asyncio
import json
import logging
import re
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi import APIRouter
from contextlib import asynccontextmanager

LOG = logging.getLogger("poc.dashboard")
logging.basicConfig(level=logging.INFO)


def topic_to_regex(pattern: str) -> str:
    # Convert a MQTT wildcard topic to regex
    pat = re.escape(pattern)
    pat = pat.replace(r"\+", "[^/]+")
    pat = pat.replace(r"\#", ".*")
    return r"^" + pat + r"$"


class Reservation:
    def __init__(self, topic: str, aip: List[str] = None, pip: List[str] = None):
        self.topic = topic
        self.aip = aip or []
        self.pip = pip or []
        self._regex = re.compile(topic_to_regex(topic))

    def matches(self, topic: str) -> bool:
        return bool(self._regex.match(topic))

    def to_dict(self):
        return {"topic": self.topic, "aip": self.aip, "pip": self.pip}

    def __repr__(self):
        return f"Reservation(topic={self.topic}, aip={self.aip}, pip={self.pip})"


class WebSocketManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active.remove(websocket)

    async def broadcast(self, message):
        to_remove = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                to_remove.append(ws)
        for r in to_remove:
            self.disconnect(r)


class DashboardBackend:
    def __init__(self, mqtt_broker: str, mqtt_port: int, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.broker = mqtt_broker
        self.port = mqtt_port
        self.loop = loop
        self.reservations: Dict[str, Reservation] = {}
        self.logs: List[dict] = []
        self.allow_without_reservation = True
        self.wsmanager = WebSocketManager()
        self.event_queue: asyncio.Queue = asyncio.Queue()

        self.mqtt = mqtt.Client(client_id="dashboard-backend")
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.on_disconnect = self._on_disconnect
        self.mqtt_connected = False

    def _log(self, level, message):
        LOG.log(level, message)
        # Timestamp using current loop if available, otherwise time.monotonic()
        try:
            ts = asyncio.get_event_loop().time()
        except Exception:
            import time

            ts = time.time()
        entry = {"ts": ts, "msg": message}
        self.logs.append(entry)
        # also send to WS via event queue if the running loop is set
        if self.loop:
            try:
                coro = self.event_queue.put({"type": "log", "data": entry})
                asyncio.run_coroutine_threadsafe(coro, self.loop)
            except Exception:
                LOG.exception("Failed to schedule log event on loop")

    def _on_connect(self, client, userdata, flags, rc):
        self._log(logging.INFO, f"Connected to MQTT broker {self.broker}:{self.port} rc={rc}")
        client.subscribe("control/reservations")
        client.subscribe("db/ack/#")
        self.mqtt_connected = True

    def _on_disconnect(self, client, userdata, rc):
        self._log(logging.WARNING, f"MQTT disconnected rc={rc}")
        self.mqtt_connected = False

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        try:
            j = json.loads(payload)
        except Exception:
            j = payload
        self._log(logging.DEBUG, f"MQTT message {topic}: {j}")
        if topic == "control/reservations":
            self._handle_reservation_message(j)
            return
        if topic.startswith("db/ack/"):
            self._handle_ack_message(topic, j)
            return
        # other messages ignored for now

    def _handle_reservation_message(self, j: dict):
        action = j.get("action")
        topic = j.get("topic")
        if action == "reserve":
            aip = j.get("aip", [])
            pip = j.get("pip", [])
            res = Reservation(topic, aip=aip, pip=pip)
            self.reservations[topic] = res
            self._log(logging.INFO, f"Added reservation {topic} (aip={aip} pip={pip})")
            # push event
            coro = self.event_queue.put({"type": "reservation", "data": res.to_dict()})
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        elif action == "unreserve":
            if topic in self.reservations:
                del self.reservations[topic]
                self._log(logging.INFO, f"Removed reservation {topic}")
                coro = self.event_queue.put({"type": "reservation-removed", "data": {"topic": topic}})
                asyncio.run_coroutine_threadsafe(coro, self.loop)
        elif j.get("action") == "clear":
            self.reservations.clear()
            self._log(logging.INFO, "Cleared reservations")
            coro = self.event_queue.put({"type": "reservation-cleared", "data": {}})
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        elif j.get("action") == "set-allow-without-res":
            val = bool(j.get("value", False))
            self.allow_without_reservation = val
            self._log(logging.INFO, f"allow_without_reservation set={val}")
            coro = self.event_queue.put({"type": "setting", "data": {"allow_without_reservation": val}})
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _handle_ack_message(self, topic: str, j: dict):
        # Acks come as {"accepted": True, "reason": "..."}
        self._log(logging.INFO, f"ACK {topic}: {j}")
        coro = self.event_queue.put({"type": "ack", "topic": topic, "data": j})
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def start(self):
        try:
            self.mqtt.connect(self.broker, self.port)
            # start mqtt loop in thread
            self.mqtt.loop_start()
        except Exception as e:
            # Log and schedule a reconnect attempt after a short delay
            self._log(logging.ERROR, f"Failed to connect to MQTT broker {self.broker}:{self.port}: {e}")
            try:
                # schedule a retry in 5 seconds
                self.loop.call_later(5, self.start)
            except Exception:
                LOG.exception("Failed to schedule MQTT reconnect")

    async def dispatch_loop(self):
        while True:
            event = await self.event_queue.get()
            try:
                await self.wsmanager.broadcast(event)
            except Exception:
                LOG.exception("Error broadcasting event")


def create_app(mqtt_broker: str, mqtt_port: int):
    # Use a lifespan handler instead of the deprecated @app.on_event('startup')
    dashboard = DashboardBackend(mqtt_broker, mqtt_port, loop=None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Obtain the running event loop from the ASGI server and start mqtt + dispatch
        running_loop = asyncio.get_event_loop()
        dashboard.loop = running_loop
        dashboard.start()
        running_loop.create_task(dashboard.dispatch_loop())
        try:
            yield
        finally:
            # Attempt clean shutdown: stop mqtt loop if running
            try:
                dashboard.mqtt.loop_stop()
            except Exception:
                pass

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="poc/frontend"), name="static")
    router = APIRouter(prefix="/api")

    @router.get("/reservations")
    async def get_reservations():
        return [r.to_dict() for r in dashboard.reservations.values()]

    @router.post("/reservations")
    async def post_reservation(req: Request):
        j = await req.json()
        topic = j["topic"]
        pip = j.get("pip", [])
        aip = j.get("aip", [])
        payload = json.dumps({"action": "reserve", "topic": topic, "pip": pip, "aip": aip})
        dashboard.mqtt.publish("control/reservations", payload)
        dashboard._log(logging.INFO, f"Requested reserve via API: {topic}")
        return {"ok": True}

    @router.delete("/reservations")
    async def delete_reservation(topic: str):
        payload = json.dumps({"action": "unreserve", "topic": topic})
        dashboard.mqtt.publish("control/reservations", payload)
        dashboard._log(logging.INFO, f"Requested unreserve via API: {topic}")
        return {"ok": True}

    @router.get("/logs")
    async def get_logs():
        return dashboard.logs[-200:]

    @router.get("/settings")
    async def get_settings():
        return {"allow_without_reservation": dashboard.allow_without_reservation}

    @router.get("/health")
    async def get_health():
        return {"mqtt_connected": bool(dashboard.mqtt_connected)}

    @router.post("/settings")
    async def set_settings(req: Request):
        j = await req.json()
        if "allow_without_reservation" in j:
            val = bool(j["allow_without_reservation"])
            payload = json.dumps({"action": "set-allow-without-res", "value": val})
            dashboard.mqtt.publish("control/reservations", payload)
            dashboard._log(logging.INFO, f"set allow_without_reservation via API: {val}")
            return {"ok": True}
        return {"ok": False}

    app.include_router(router)

    @app.get("/")
    async def root():
        return RedirectResponse(url="/static/index.html")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await dashboard.wsmanager.connect(websocket)
        try:
            while True:
                # Wait for client pings or ignore messages
                msg = await websocket.receive_text()
                # Fast protocol: clients can request state
                if msg == "state":
                    await websocket.send_json({"type": "state", "data": {"reservations": [r.to_dict() for r in dashboard.reservations.values()], "settings": {"allow_without_reservation": dashboard.allow_without_reservation}}})
        except WebSocketDisconnect:
            dashboard.wsmanager.disconnect(websocket)

    # NOTE: the old @app.on_event startup handler was removed in favor of the
    # lifespan handler defined above. The lifespan handler is responsible for
    # setting `dashboard.loop`, starting the MQTT client and scheduling the
    # dispatch loop on the correct running event loop.

    return app

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port-http", type=int, default=8000)
    args = parser.parse_args()
    import uvicorn

    loop = asyncio.get_event_loop()
    app = create_app(args.broker, args.port)
    uvicorn.run(app, host=args.host, port=args.port_http)


if __name__ == "__main__":
    main()
