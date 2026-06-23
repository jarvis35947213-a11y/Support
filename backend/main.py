import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(_ROOT, "frontend")

app = Flask(__name__, static_folder=_FRONTEND, static_url_path="")
CORS(app)

# Хранилище сообщений (в памяти — переживает только один инстанс)
messages = []
DATA_FILE = os.environ.get("DATA_FILE", "/tmp/support_messages.json")


def _load():
    global messages
    try:
        with open(DATA_FILE) as f:
            messages = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        messages = []


def _save():
    with open(DATA_FILE, "w") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


@app.route("/api/messages", methods=["GET"])
def get_messages():
    _load()
    return jsonify(messages)


@app.route("/api/messages", methods=["POST"])
def add_message():
    data = request.get_json(force=True)
    now = datetime.utcnow().isoformat() + "Z"
    msg = {
        "text": data.get("text", ""),
        "role": data.get("role", "user"),
        "ts": data.get("ts", now),
    }
    _load()
    messages.append(msg)
    _save()
    return jsonify(msg), 201


@app.route("/api/messages", methods=["DELETE"])
def clear_messages():
    _load()
    messages.clear()
    _save()
    return jsonify({"ok": True})


# Раздача фронтенда
@app.route("/")
def index():
    return send_from_directory(_FRONTEND, "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(_FRONTEND, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
