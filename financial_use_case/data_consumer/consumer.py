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
MCP_CLIENT_URL = os.environ.get("MCP_CLIENT_URL", "http://mcp-client-service:8000/chat")
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
        logging.debug("Requesting retained message for topic=%s via %s", topic, mcp_url)
        # Simple non-configurable retry: 3 attempts with 1s fixed sleep
        max_attempts = 3
        sleep_time = 1
        # MCP /chat expects: {"message": "<string>", "session_id": "<id>"}
        chat_payload = {
            "message": json.dumps(payload),
            "session_id": payload["request_id"],
        }

        for attempt in range(1, max_attempts + 1):
            try:
                logging.info("Sending request to MCP (attempt %d/%d) topic=%s", attempt, max_attempts, topic)
                logging.debug("Outgoing chat_payload: %s", chat_payload)
                r = requests.post(mcp_url, json=chat_payload, timeout=timeout)

                logging.info("Received HTTP %s from MCP", r.status_code)
                logging.debug("Response headers: %s", dict(r.headers))

                if 200 <= r.status_code < 300:
                    try:
                        body = r.json()
                    except Exception:
                        logging.warning("Response not JSON, returning raw text")
                        body = {"raw": r.text}

                    return {"status": "ok", "http_status": r.status_code, "body": body}

                # Non-2xx responses: log body and retry only on 5xx
                resp_text = r.text
                logging.error("MCP returned non-2xx status=%s body=%s", r.status_code, resp_text)

                if r.status_code >= 500 and attempt < max_attempts:
                    logging.info("Server error; retrying after %ds (attempt %d/%d)", sleep_time, attempt, max_attempts)
                    time.sleep(sleep_time)
                    continue

                try:
                    err_body = r.json()
                except Exception:
                    err_body = {"raw": resp_text}

                return {"status": "error", "http_status": r.status_code, "body": err_body, "url": mcp_url}

            except requests.RequestException as e:
                logging.warning("Request attempt %d failed with exception: %s", attempt, e)
                if attempt < max_attempts:
                    logging.info("Network error; retrying after %ds (attempt %d/%d)", sleep_time, attempt, max_attempts)
                    time.sleep(sleep_time)
                    continue
                logging.exception("All attempts to contact MCP have failed")
                return {"status": "error", "message": "MCP client unreachable after retries", "url": mcp_url}

consumer = DataConsumer()
app = Flask(__name__)

@app.route("/retrieve_retained", methods=["POST"])
def retrieve_retained():
    data = request.get_json()
    topic = data.get("topic", RETAINED_TOPIC_ENV)
    logging.debug("Received retrieve_retained request for topic=%s", topic)
    try:
        if not topic:
            raise ValueError("No topic provided in request or RETAINED_TOPIC env var")
    except Exception as e:
        logging.error("Error in request: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 400 
    result = consumer.request_retained_message(topic=topic, mcp_url=MCP_CLIENT_URL)
    # If result-> body ->response is empty then log an error
    if not result.get("body", {}).get("response"):
        logging.error("No retained message found for topic=%s or an error occurred", topic)
        return jsonify({"status": "error", "message": "No retained message found or an error occurred"}), 404
    else:
        
        logging.debug("retrieve_retained result: %s", result)
    # Return the retrieved message as part of the response
    return jsonify({"status": "ok", "message": "Message received", "data": result}), 200 if result.get("status") == "ok" else 500

if __name__ == "__main__":
    if INITIAL_RUN:
        try:
            result = consumer.request_retained_message(topic=RETAINED_TOPIC_ENV, mcp_url=MCP_CLIENT_URL)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            # fail fast if initial run did not succeed
            if result.get("status") != "ok":
                logging.error("Initial MCP request failed: %s", result)
                raise SystemExit(1)
        except Exception:
            logging.exception("Initial MCP request failed, exiting")
            raise

    app.run(host="0.0.0.0", port=8090)