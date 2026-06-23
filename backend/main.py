import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(_ROOT, "frontend")

app = Flask(__name__, static_folder=_FRONTEND, static_url_path="")
CORS(app)

DATA_FILE = os.environ.get("DATA_FILE", "/tmp/support_data.json")

def _load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"conversations": {}, "registrations": {}}

def _save(data):
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Регистрация клиента ──────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def register():
    body = request.get_json(force=True)
    client_id = body.get("client_id", "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    data = _load()
    reg = data.setdefault("registrations", {})
    if client_id not in reg:
        reg[client_id] = datetime.utcnow().isoformat() + "Z"
    if client_id not in data.setdefault("conversations", {}):
        data["conversations"][client_id] = []
    _save(data)
    return jsonify({
        "client_id": client_id,
        "registered_at": reg[client_id],
        "ok": True
    })

# ── Сообщения для конкертного клиента ─────────────────────────────
@app.route("/api/messages/<client_id>", methods=["GET"])
def get_messages(client_id):
    data = _load()
    msgs = data.get("conversations", {}).get(client_id, [])
    return jsonify(msgs)

@app.route("/api/messages/<client_id>", methods=["POST"])
def add_message(client_id):
    body = request.get_json(force=True)
    now = datetime.utcnow().isoformat() + "Z"
    msg = {
        "text": body.get("text", ""),
        "role": body.get("role", "user"),
        "ts": body.get("ts", now),
    }
    data = _load()
    conv = data.setdefault("conversations", {}).setdefault(client_id, [])
    conv.append(msg)
    _save(data)
    return jsonify(msg), 201

@app.route("/api/messages/<client_id>", methods=["DELETE"])
def clear_messages(client_id):
    data = _load()
    data.setdefault("conversations", {})[client_id] = []
    _save(data)
    return jsonify({"ok": True})

# ── Список всех обращений (для дашборда поддержки) ───────────────
@app.route("/api/conversations", methods=["GET"])
def list_conversations():
    data = _load()
    convs = data.get("conversations", {})
    regs = data.get("registrations", {})
    result = []
    for cid, msgs in convs.items():
        last_ts = ""
        preview = ""
        if msgs:
            last_ts = msgs[-1].get("ts", "")
            preview = msgs[-1].get("text", "")
        result.append({
            "client_id": cid,
            "registered_at": regs.get(cid, ""),
            "last_ts": last_ts,
            "preview": preview,
            "count": len(msgs),
        })
    result.sort(key=lambda c: c["last_ts"], reverse=True)
    return jsonify(result)

# ── Раздача фронтенда ──────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(_FRONTEND, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(_FRONTEND, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
