import os
import time
import uuid
import json
import uuid
import logging
from threading import Event

import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# URL of the LLM endpoint 
LLM_URL = os.environ.get("LLM_URL", "http://mock-llm:5000")
# Name of the fictional store that sends receipts
MANDANT_ID = os.environ.get("MANDANT_ID", "mandant_1234")
# amount of messages to send 
NUM_MESSAGES = int(os.environ.get("NUM_MESSAGES", "0"))
# Timeout for POST requests to the LLM endpoint
POST_TIMEOUT = int(os.environ.get("POST_TIMEOUT", "10"))
# system prompt: env var, fallback to file
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT")
if not SYSTEM_PROMPT:
    prompt_file = os.environ.get("SYSTEM_PROMPT_FILE", "system_prompt.txt")
    try:
        with open(prompt_file, "r", encoding="utf8") as f:
            SYSTEM_PROMPT = f.read().strip()
    except FileNotFoundError:
        SYSTEM_PROMPT = "You are an assistant that gets a receipe or a retained message from a POS terminal. Your Job is to ectact the Intend and Purpose of this transaction and send it to a Broker that has PBAC using you MCP server."

app = Flask(__name__)


class PosClient:
    """ A simple POS client that generates sample receipts and sends them to an LLM endpoint.
    """
    def __init__(self):
        """ Initialize the POS client."""
        self.stop_event = Event()

    def generate_sample_receipt(self, idx: int):
        """Generate a sample receipt with given index."""
        rid = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {
            "id": rid,
            "timestamp": now,
            "signature": f"sha256:deadbeef{idx}",
            "items": [
                {"name": "ItemA", "qty": 2, "net": 3.00, "vat": 7},
                {"name": "ItemB", "qty": 1, "net": 2.80, "vat": 19},
            ],
            "total_gross": 8.80,
            "payment_method": "card",
            "cancellation_flag": False,
            "cashier_id": "maxmustermann",
            "store_id": MANDANT_ID,
        }

    def build_context(self, receipts):
        return {
            "request_id": str(uuid.uuid4()),
            "mandant_id": MANDANT_ID,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payload_type": "batch" if len(receipts) > 1 else "single",
            "receipts": receipts,
            "retained_summaries": [],
            "instructions": {
                "system_prompt": SYSTEM_PROMPT,
                "analysis": "aggregate_vat_by_rate",
                "return_format": "llm_response_v1"
            }
        }

    def compute_retained_summary(self, receipts, period: str = None):
        """
        Compute a retained summary (simple aggregation) from a list of receipts.
        Returns a dict suitable for sending as a retained message.
        """
        total_sales = 0.0
        total_transactions = len(receipts)
        vat_by_rate = {}

        for r in receipts:
            total_sales += float(r.get("total_gross", 0.0))
            for item in r.get("items", []):
                rate = str(item.get("vat", "0"))
                qty = float(item.get("qty", 1))
                net = float(item.get("net", 0.0))
                vat_amount = net * qty * (float(item.get("vat", 0)) / 100.0)
                vat_by_rate[rate] = vat_by_rate.get(rate, 0.0) + vat_amount

        summary = {
            "type": "summary",
            "period": period or time.strftime("%Y-%m-%d", time.gmtime()),
            "store_id": MANDANT_ID,
            "total_sales": round(total_sales, 2),
            "total_transactions": total_transactions,
            "vat_by_rate": {k: round(v, 2) for k, v in vat_by_rate.items()},
        }
        return summary

    def post_to_llm(self, context):
        req_id = context["request_id"]
        for attempt in range(1, 4):
            try:
                logging.info(f"POSTing context request_id={req_id} to LLM (attempt {attempt})")
                r = requests.post(LLM_URL, json=context, timeout=POST_TIMEOUT)
                r.raise_for_status()
                logging.info(f"LLM accepted request_id={req_id} status={r.status_code}")
                return r
            except Exception as e:
                logging.warning(f"LLM POST failed for request_id={req_id}: {e}")
                time.sleep(1 * attempt)
        logging.error(f"LLM unreachable for request_id={req_id}")
        return None

    def run_once(self, num_messages=1):
        receipts = [self.generate_sample_receipt(i) for i in range(num_messages)]
        context = self.build_context(receipts)
        response = self.post_to_llm(context)
        if response is None:
            return {"status": "error", "message": "LLM unreachable"}, 503

        try:
            body = response.json()
        except Exception:
            body = response.text
        return {"status": "accepted", "request_id": context["request_id"], "llm_status": response.status_code, "llm_body": body}, response.status_code


client = PosClient()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/trigger", methods=["POST"])
def trigger():
    data = request.get_json(silent=True) or {}
    num = int(data.get("num_messages", 1))
    mode = data.get("mode", "receipt")  # 'receipt' or 'retained'
    logging.info(f"HTTP trigger received: mode={mode} num_messages={num}")

    # Generate sample receipts
    receipts = [client.generate_sample_receipt(i) for i in range(num)]

    if mode == "retained":
        # Client computes the retained summary and asks the LLM/MCP to store it as a retained message
        summary = client.compute_retained_summary(receipts)
        # Build a context that instructs the LLM/MCP to publish the retained summary (not stream)
        context = client.build_context([])
        context["payload_type"] = "retained_summary"
        context["receipts"] = []
        context["retained_summaries"] = [summary]
        context["instructions"] = {
            "action": "store_retained",
            "publish_topic": f"sales_summaries/{MANDANT_ID}/retained",
            "return_format": "ack",
        }
        response = client.post_to_llm(context)
        if response is None:
            return jsonify({"status": "error", "message": "LLM unreachable"}), 503
        try:
            body = response.json()
        except Exception:
            body = response.text
        return jsonify({"status": "accepted", "request_id": context["request_id"], "llm_status": response.status_code, "llm_body": body}), response.status_code

    # default: send plain receipt(s) via LLM for further processing
    result, status = client.run_once(num_messages=num)
    return jsonify(result), status


def main():
    # Optionally run an initial job if NUM_MESSAGES > 0
    if NUM_MESSAGES > 0:
        logging.info(f"Initial run at startup: num_messages={NUM_MESSAGES}")
        client.run_once(num_messages=NUM_MESSAGES)
    # Start HTTP server to accept triggers
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

