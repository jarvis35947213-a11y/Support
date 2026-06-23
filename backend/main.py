import os
import json
import base64
import hashlib
import secrets
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND = os.path.join(_ROOT, "frontend")

app = Flask(__name__, static_folder=_FRONTEND, static_url_path="")
CORS(app)

DATA_FILE = os.environ.get("DATA_FILE", "/tmp/support_data.json")
PASSWORD = "Yfep2224"
SECRET_KEY = secrets.token_hex(32)

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

def _make_token():
    raw = f"{PASSWORD}:{SECRET_KEY}"
    return base64.b64encode(hashlib.sha256(raw.encode()).hexdigest().encode()).decode()

def _check_auth():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:] == _make_token():
        return True
    return False

def _check_auth_or_403():
    if not _check_auth():
        return jsonify({"error": "Unauthorized"}), 403
    return None

@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(force=True)
    pw = body.get("password", "")
    if pw != PASSWORD:
        return jsonify({"error": "Invalid password"}), 401
    return jsonify({"token": _make_token(), "ok": True})

# ── Регистрация клиента ──
@app.route("/api/register", methods=["POST"])
def register():
    body = request.get_json(force=True)
    client_id = body.get("client_id", "").strip()
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    data = _load()
    reg = data.setdefault("registrations", {})
    if client_id not in reg:
        reg[client_id] = datetime.now(timezone.utc).isoformat()
    if client_id not in data.setdefault("conversations", {}):
        data["conversations"][client_id] = {"messages": [], "status": "open"}
    _save(data)
    return jsonify({
        "client_id": client_id,
        "registered_at": reg[client_id],
        "ok": True
    })

# ── Сообщения ──
@app.route("/api/messages/<client_id>", methods=["GET"])
def get_messages(client_id):
    data = _load()
    conv = data.get("conversations", {}).get(client_id, {})
    msgs = conv.get("messages", []) if isinstance(conv, dict) else []
    return jsonify(msgs)

@app.route("/api/messages/<client_id>", methods=["POST"])
def add_message(client_id):
    body = request.get_json(force=True)
    now = datetime.now(timezone.utc).isoformat()
    msg = {
        "text": body.get("text", ""),
        "role": body.get("role", "user"),
        "ts": body.get("ts", now),
    }
    data = _load()
    conv = data.setdefault("conversations", {}).setdefault(client_id, {"messages": [], "status": "open"})
    if isinstance(conv, list):
        conv = {"messages": conv, "status": "open"}
        data["conversations"][client_id] = conv
    conv.setdefault("messages", []).append(msg)
    _save(data)
    return jsonify(msg), 201

@app.route("/api/messages/<client_id>", methods=["DELETE"])
def clear_messages(client_id):
    auth_err = _check_auth_or_403()
    if auth_err: return auth_err
    data = _load()
    conv = data.setdefault("conversations", {}).get(client_id, {})
    if isinstance(conv, dict):
        conv["messages"] = []
    else:
        data["conversations"][client_id] = {"messages": [], "status": "open"}
    _save(data)
    return jsonify({"ok": True})

# ── Управление статусом обращения ──
@app.route("/api/conversations/<client_id>/close", methods=["POST"])
def close_conversation(client_id):
    auth_err = _check_auth_or_403()
    if auth_err: return auth_err
    data = _load()
    conv = data.setdefault("conversations", {}).get(client_id, {})
    if isinstance(conv, list):
        conv = {"messages": conv, "status": "closed"}
        data["conversations"][client_id] = conv
    elif isinstance(conv, dict):
        conv["status"] = "closed"
    _save(data)
    return jsonify({"ok": True, "status": "closed"})

@app.route("/api/conversations/<client_id>/reopen", methods=["POST"])
def reopen_conversation(client_id):
    auth_err = _check_auth_or_403()
    if auth_err: return auth_err
    data = _load()
    conv = data.setdefault("conversations", {}).get(client_id, {})
    if isinstance(conv, list):
        conv = {"messages": conv, "status": "open"}
        data["conversations"][client_id] = conv
    elif isinstance(conv, dict):
        conv["status"] = "open"
    _save(data)
    return jsonify({"ok": True, "status": "open"})

# ── Список всех обращений ──
@app.route("/api/conversations", methods=["GET"])
def list_conversations():
    data = _load()
    convs = data.get("conversations", {})
    regs = data.get("registrations", {})
    result = []
    for cid, conv in convs.items():
        msgs = conv.get("messages", []) if isinstance(conv, dict) else (conv if isinstance(conv, list) else [])
        status = conv.get("status", "open") if isinstance(conv, dict) else "open"
        last_ts = ""
        preview = ""
        if msgs and len(msgs) > 0:
            last_ts = msgs[-1].get("ts", "")
            preview = msgs[-1].get("text", "")
        result.append({
            "client_id": cid,
            "registered_at": regs.get(cid, ""),
            "last_ts": last_ts,
            "preview": preview,
            "count": len(msgs),
            "status": status,
        })
    result.sort(key=lambda c: c["last_ts"], reverse=True)
    return jsonify(result)

# ── Раздача фронтенда ──
@app.route("/")
def index():
    return send_from_directory(_FRONTEND, "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(_FRONTEND, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
