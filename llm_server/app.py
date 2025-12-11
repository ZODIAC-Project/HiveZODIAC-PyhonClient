"""Mock LLM server

Provides a tiny Flask-based mock LLM API for local testing. Endpoints:
 - GET /health        : health check
 - POST /generate     : accepts JSON {"input": "..."} (or "prompt"/"text")
                       and returns a structured response similar to an LLM.
"""

from flask import Flask, request, jsonify
import logging
import os

app = Flask(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def mock_extract(prompt: str):
    """Create a trivial structured response from the prompt.

    This keeps responses deterministic and simple for testing the client.
    """
    p = (prompt or "").strip()
    text = f"Mocked LLM response for prompt: {p[:200]}"

    # Simple heuristics to populate purpose/intent
    purpose = "general"
    intent = "answer"
    if "sales" in p.lower():
        purpose = "sales_report"
        intent = "aggregate"
    elif "volume" in p.lower() or "loud" in p.lower():
        purpose = "control_device"
        intent = "adjust_setting"

    result = {
        "text": text,
        "purpose": purpose,
        "intent": intent,
        "metadata": {"mock": True}
    }
    return result


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/generate", methods=["POST"])
def generate():
    if request.is_json:
        body = request.get_json()
    else:
        # try form or raw text
        body = {"text": request.form.get("text") or request.data.decode("utf-8")}

    text = body.get("input") or body.get("prompt") or body.get("text")
    if not text:
        return jsonify({"error": "missing input/prompt/text"}), 400

    logger.info("Received prompt: %s", (text[:200] + "...") if len(text) > 200 else text)

    result = mock_extract(text)

    # Return in a 'response' key to match the client expectations
    return jsonify({"response": result})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
