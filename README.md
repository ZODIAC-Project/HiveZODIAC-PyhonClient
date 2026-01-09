# HiveZODIAC Client

This Repository contains functional testing of the HiveZODIAC PBAC Broker extension and a proof of work implementation of a financial use case. It also holds a monitoring stack that can run along the use case.

Install and run with [uv](https://docs.astral.sh/uv/)!

## Components and files in this repository
**Purpose_client.py:**
    A Purpose-Aware MQTT Client that uses a Paho Client under the Hood.
    It sends, subscribes and reserves channels for given purposes and allows
    to keep track of which messages should or should not be received to
    test the robustness of a PBAC system.

**Functional_test.py:**
    A Functional Test Demo that simulates a full scenario of reservation/subscription/publish workflows to verify the MQTTBrokers behavior.

**financial_use_case folder**
This repository contains a proof-of-concept implementation of a financial use case.
--- 

**More Information:**

For details on components of the prove of concept financial use case and how to deploy it, see the [financial_use_case/README.md](financial_use_case/README.md).

For information and instructions on how to deploy the monitoring stack, see the [monitoring/README.md](monitoring/README.md).