import os
import time
import uuid
import json
import logging
from typing import Any, Dict

import requests
from flask import Flask, request, jsonify

LOGGING_LEVEL = os.environ.get("LOGGING_LEVEL", "INFO").upper()
logging.getLogger().setLevel(LOGGING_LEVEL)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Environment configuration
# topic has to be provided explicitly via env: sales_summaries/<mandant>/retained
#TODO: Add dynamic mandant_id handling
RETAINED_TOPIC_ENV = os.environ.get("RETAINED_TOPIC")
MCP_CLIENT_URL = os.environ.get("MCP_CLIENT_URL", "http://mcp-client:8000/retrieve")
INITIAL_RUN = os.environ.get("INITIAL_RUN", "false").lower() == "true"
# system prompt: env var, fallback to file
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT")
if not SYSTEM_PROMPT:
    prompt_file = os.environ.get("SYSTEM_PROMPT_FILE", "system_prompt.txt")
    try:
        with open(prompt_file, "r", encoding="utf8") as f:
            SYSTEM_PROMPT = f.read().strip()
    except FileNotFoundError:
        SYSTEM_PROMPT = "Retrieve the retained MQTT message for the given topic and return it as JSON."

class DataConsumer:

    def build_mcp_payload(self, topic) -> Dict[str, Any]:
        """Create the payload to send to the MCP client
        """
        return {
            "request_id": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "instructions": {
                "action": "retrieve_retained",
                "topic": topic,
                "return_format": "json",
                "system_prompt": SYSTEM_PROMPT,
            },
        }


    def request_retained_message(self, topic, mcp_url, timeout: int = 10) -> Dict[str, Any]:
        """Ask the MCP client to retrieve the retained message for `topic`.
        """
        payload = self.build_mcp_payload(topic)
        logging.info("Requesting retained message for topic=%s via %s", topic, mcp_url)
        # Simple retry loop
        for attempt in range(1, 4):
            try:
                logging.debug("POST attempt %d to %s: %s", attempt, mcp_url, payload)
                r = requests.post(mcp_url, json=payload, timeout=timeout)
                r.raise_for_status()
                try:
                    body = r.json()
                except Exception:
                    body = {"raw": r.text}

                logging.info("Received response status=%s", r.status_code)
                return {"status": "ok", "http_status": r.status_code, "body": body}
            except requests.RequestException as e:
                logging.warning("Request attempt %d failed: %s", attempt, e)
                time.sleep(attempt)

        return {"status": "error", "message": "MCP client unreachable after retries", "url": mcp_url}

consumer = DataConsumer()
app = Flask(__name__)

@app.route("/retrieve_retained", methods=["POST"])
def retrieve_retained():
    data = request.get_json()
    topic = data.get("topic", RETAINED_TOPIC_ENV)
    result = consumer.request_retained_message(topic=topic, mcp_url=MCP_CLIENT_URL)
    return jsonify(result)

if __name__ == "__main__":
    
    if INITIAL_RUN == True:
        result = consumer.request_retained_message(topic=RETAINED_TOPIC_ENV, mcp_url=MCP_CLIENT_URL)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    app.run(host="0.0.0.0", port=8090)