Minimal Setup: broker-mediated DB access control using reservation policies
=============================================================

## Overview
--------
This poc shows the interaction between an MQTT broker, a backend that persists data to a database (SQLite), and a reservation system that controls which topics are allowed to write to the database. This Readme describes the components and how to run the Poc locally. For instructions on how to run the poc using Docker/Kubernetes, see the `k8s/README.md`.

Files: 
------------
- `backend.py` — ingest backend that:
  - subscribes to `control/reservations` and to `db/ingest/#`,
  - enforces topic-level reservations,
  - writes accepted messages to SQLite (`poc.db` by default), and
  - publishes ACKs on `db/ack/<client>/<msg_id>`.
- `client_publisher.py` — example publisher that sends an ingest message and waits for an ACK.
- `reserve.py` — helper CLI to publish reservation commands (reserve, unreserve, set allow-without-res).
- `dashboard_backend.py` + `frontend/index.html` — small FastAPI-based dashboard (REST + WebSocket) and static frontend to view and control reservations and logs.


## Steps to run the PoC
1. Start a MQTT broker and make sure it's reachable at `localhost:1883`:
- For an example, you can look at the [HiveZODIAC Client README]( https://github.com/ZODIAC-Project/HiveZODIAC/blob/main/README.md)

2. Start the backend (ingest + reservation enforcement)

The backend gets configurations via environment variables. Example variables:

- `BROKER_HOST` (default: `localhost`)
- `BROKER_PORT` (default: `1883`)
- `DB_PATH` (default: `poc.db`)
- `MQTT_USER` / `MQTT_PASSWORD` (optional)
- `ALLOW_WITHOUT_RESERVATION` (`true` or `false`, default: `true`)

Run locally with `uv` (example):

```zsh
export BROKER_HOST=localhost
export BROKER_PORT=1883
export DB_PATH=poc.db
uv run poc/backend.py
```

Or run the backend in a container / docker with env variables set:

```zsh
docker run --rm -e BROKER_HOST=mqtt-broker -e BROKER_PORT=1883 your-image:tag
```
3. Start the dashboard (REST + WebSocket UI) in a new terminal

The dashboard still accepts environment variables for broker configuration. See the `dashboard_backend.py` help or use the same `BROKER_HOST` / `BROKER_PORT` env vars as above.

Example (local):

```zsh
export BROKER_HOST=localhost
export BROKER_PORT=1883
uv run poc/dashboard_backend.py
```

4. Open the UI in your browser:

```
http://localhost:8001/
```
5. Create a reservation in a new terminal

```zsh
uv run poc/reserve.py reserve --topic "db/ingest/user/#" --pip ingest
```
The dashboard will display the new reservation (and the backend sees the `control/reservations` message).
The reservation can also be checked using the REST API: `GET /api/reservations`
```zsh
curl http://localhost:8001/api/reservations
```

6. Publish an ingest message (simulate a client)

Send an example message; the backend enforces topic-level reservations.

```zsh
uv run poc/client_publisher.py --client-id c1 --user user-123 \
  --topic db/ingest/user/user-123 --purpose ingest --data '{"value": 42}'
```

Expected behavior:
- The backend checks for a matching reservation for the topic.
- If allowed, the backend writes a record into `poc.db` and publishes an ACK to `db/ack/c1/<msgid>`.
- The dashboard shows the ACK in its log view. 
