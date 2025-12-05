# HiveZODIAC Client

This Repository contains functional testing and and example proof-of-concept deployment for the HiveZODIAC MQTT-Broker.

Install and run with [uv](https://docs.astral.sh/uv/)!

## Components
**Purpose-client:**
    A Purpose-Aware MQTT Client that uses a Paho Client under the Hood.
    It sends, subscribes and reserves channels for given purposes and allows
    to keep track of which messages should or should not be received to
    test the robustness of a PBAC system.

**Functional-test:**
    A Functional Test Demo that simulates a full scenario of reservation/subscription/publish workflows to verify the MQTTBrokers behavior.

**Minimal-PoC: MQTT-based Reservation System**
This repository contains a proof-of-concept implementation of an MQTT-based reservation system that simulates a publish-subscribe architecture with reservation control for database writes.
--- 

**More Information:**


For details on components of the poc and how to deploy it, see the [poc/README.md](poc/README.md).

For instructions on how to run the poc using Docker/Kubernetes, see the [k8s/README.md](k8s/README.md).

For information and instructions on how to deploy monitoring stack with Prometheus and Grafana, see the [monitoring/README.md](monitoring/README.md).