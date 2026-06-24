import os
import json
import base64
import hashlib
import secrets
import requests as http
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

# ── AI-подсказка ответа (Gemini через Polza.ai) ──
AI_KEY = os.environ.get("GEMINI_API_KEY", "pza_MDZgRqsIDd-IdthdUYf5n3HVzpisuOuR")
AI_URL = os.environ.get("GEMINI_API_URL", "https://polza.ai/api/v1/chat/completions")
AI_MODEL = os.environ.get("GEMINI_MODEL", "google/gemini-3.1-flash-lite")

SYSTEM_PROMPT = (
    "Ты — ассистент поддержки Jarvis Desktop. "
    "Ниже история переписки с пользователем. Напиши ВЕЖЛИВЫЙ и ПОЛЕЗНЫЙ ответ от лица поддержки "
    "на РУССКОМ языке.вот базавые проблеммы и их решения # Шпаргалка поддержки Jarvis — готовые ответы 1.0–30.0
# Копируйте и вставляйте нужный пункт, подставляя {имя} если нужно.

--- 1.0 Приложение не запускается ---
Проверьте, что у вас установлен Microsoft Visual C++ Redistributable (x64). Скачайте с https://aka.ms/vs/17/release/vc_redist.x64.exe
Если уже установлен — удалите папку %appdata%\JARVIS\JarvisV2\config.json и запустите заново. Конфиг пересоздастся автоматически.

--- 2.0 Чёрный экран при запуске ---
Убедитесь, что в папке с программой есть папка platforms/ и в ней qwindows.dll. Если нет — переустановите приложение.
Также проверьте, не блокирует ли антивирус jarvis.exe (добавьте в исключения).

--- 3.0 Не работает микрофон (голосовой ввод) ---
Проверьте в настройках Windows: Параметры → Конфиденциальность → Микрофон — разрешите приложениям доступ.
В приложении нажмите на иконку микрофона — если она перечёркнута, значит нет доступа.

--- 4.0 Распознавание речи не работает / не слышит ---
Убедитесь, что модель Vosk загружена: в папке models/ должна быть папка vosk-model-small-ru.
Размер модели ~42 МБ. Если папка пустая — скачайте вручную с https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip и распакуйте в models/.

--- 5.0 Английский распознаётся как русский ---
Приложение автоматически определяет язык по confidence слов. Если проблема постоянная — в Config.cpp можно понизить порог RU: найдите строку threshold = 0.15 и увеличьте до 0.3–0.5, пересоберите.

--- 6.0 Не отвечает / зависает после команды — 6.0 ---
Проверьте подключение к интернету. Без сети не работают AI-бэкенды (Groq/Gemini) и TTS (Polza/Salute).
Откройте логи: %appdata%\JARVIS\JarvisV2\logs\jarvis.log — найдите последнюю ошибку перед зависанием.

--- 7.0 Медленно работает / тормозит ---
1. Проверьте, что используется видеокарта, а не встроенная графика (настройки NVIDIA/AMD).
2. Уменьшите скорость анимаций в настройках (animationSpeed = 0.5).
3. Отключите визуализатор голоса или выберите стиль "bars" (самый лёгкий).
4. Проверьте загрузку CPU в диспетчере задач.

--- 8.0 Не работает голос (TTS) — 8.0 ---
Откройте настройки → «Голос ассистента». Попробуйте переключить:
- "polza" — онлайн, нужен интернет
- "soundpack" — офлайн, нужны WAV-файлы
- "qt" — системный голос Windows (Edge), работает без интернета
Если ничего не работает — переключитесь на "qt".

--- 9.0 Звук прерывается / заикается при ответе ---
Проверьте версию драйвера аудиокарты. Отключите "Улучшения звука" в свойствах динамиков (панель управления → звук).
В настройках TTS попробуйте выключить потоковое воспроизведение (если есть опция).

--- 10.0 Ошибка "Model not found" при запуске ---
Модели Vosk не скопировались в build/. Переустановите приложение или скачайте модели вручную:
- Русская: https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip → models/vosk-model-small-ru/
- Английская: https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip → models/vosk-model-small-en/

--- 11.0 Не открываются обои / фон чёрный ---
Проверьте, что в папке backgrounds/ есть изображения. Если нет — скачайте любые обои и укажите путь в настройках вручную.
Фон может не загружаться если изображение слишком большое (>10 МБ).

--- 12.0 Не срабатывают напоминания ---
Напоминания работают только когда приложение запущено. Проверьте, что оно не свёрнуто в трей.
Также проверьте, не отключены ли уведомления Windows для jarvis.exe.

--- 13.0 Не открывается ссылка / сайт ---
По умолчанию открывается в браузере по умолчанию. Проверьте настройки браузера.
Если используется "Открыть в Telegram" — нужен установленный Telegram Desktop.

--- 14.0 Медиа-плеер не видит музыку ---
Плеер сканирует папку Музыка/ и downloads/. Форматы: mp3, wav, flac, ogg.
Если музыка не появляется — перезапустите приложение или нажмите «Обновить» в плеере.

--- 15.0 Не работает AI-функция (ответы, советы) ---
Проверьте интернет. AI-бэкенд использует Groq или Gemini через Polza.ai прокси.
Если ошибка "API key error" — обратитесь к разработчику, ключи могли закончиться.
Попробуйте переключить бэкенд: Groq → Gemini или наоборот (в Config.cpp или соберите с флагом).

--- 16.0 Приложение не обновляется ---
Последнюю версию скачивайте с канала: https://t.me/+c2w3qzhvPzM0ODAy
Просто установите сверху — данные сохранятся. Если нужно чисто — удалите через «Удаление программы» и выберите «Удалить все данные».

--- 17.0 Сброс всех настроек ---
Закройте приложение. Удалите файл: %appdata%\JARVIS\JarvisV2\config.json
При следующем запуске config.json создастся заново с настройками по умолчанию.

--- 18.0 Где находятся логи? ---
Логи: %appdata%\JARVIS\JarvisV2\logs\jarvis.log
Откройте и найдите последнюю запись [ERROR] или [WARN] — это поможет диагностировать проблему.

--- 19.0 Как открыть консоль разработчика? ---
Нажмите Ctrl+Shift+I в окне приложения. Откроется QML-инспектор (только в debug-сборке).
В release-сборке откройте CMD и запустите: set QML_LOGGING=debug && jarvis.exe

--- 20.0 Не выполняются команды (открыть приложение, сайт) ---
Проверьте, что в Config.cpp правильно указаны app_id для ваших приложений.
По умолчанию: chrome, telegram, discord, spotify, notepad, calc, explorer.
Если ваше приложение не открывается — напишите нам его точное название和执行able path.

--- 21.0 Не срабатывает wake-word (Jarvis) ---
Убедитесь, что в настройках включён «Детектор wake-word».
Попробуйте произнести чётче: "Джарвис" (с ударением на первый слог).
Если микрофон отключается после первого срабатывания — перезапустите приложение.

--- 22.0 Визуализатор голоса не отображается ---
В настройках проверьте «Стиль визуализатора» — выберите sine / bars / radial / pulse.
speed анимации (animationSpeed) должна быть > 0.25.

--- 23.0 Ошибка "SSL handshake failed" ---
Проверьте системную дату и время — они должны быть точными.
Обновите OpenSSL: https://slproweb.com/products/Win32OpenSSL.html (скачайте Win64 OpenSSL v3.x).
Или добавьте флаг в config.json: "backendInsecure": true (отключает проверку сертификатов, не рекомендуется).

--- 24.0 Приложение долго грузится (30+ секунд) ---
При первом запуске Vosk модель загружается в память — это может занять до 10 секунд.
Последующие запуски быстрее.
Если грузится >30 секунд — возможно проблема с диском (HDD вместо SSD) или антивирус сканирует модель.

--- 25.0 Не применяются изменения в Config.cpp после сборки ---
После изменения Config.cpp нужно пересобрать проект: запустите build.bat из папки JarvisV2.
Убедитесь, что ninja завершился без ошибок. Проверьте build_output.txt на наличие [error].

--- 26.0 Ошибка "Vosk model path resolved: false" ---
Модели не скопированы в папку сборки. Запустите сборку через build.bat (POST_BUILD шаг копирует модели).
Если models/ в папке сборки пустая — скопируйте вручную папку models/vosk-model-small-ru из исходников.

--- 27.0 Как добавить новый QML файл? ---
Пропишите его в CMakeLists.txt в секции QML_FILES внутри qt_add_qml_module.
После добавления — пересоберите проект. Иначе QML-движок не найдёт тип.

--- 28.0 Ошибка при сборке (C++ компилятор) ---
Запустите build.bat из-под vcvarsall.bat:
"call C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
Затем: cmake -G Ninja -S C:\JarvisV2 -B C:\JarvisV2\build -DCMAKE_PREFIX_PATH=C:/Qt/6.7.2/msvc2019_64
И: ninja -C C:\JarvisV2\build

--- 29.0 Не работает чат поддержки в приложении ---
Убедитесь, что есть интернет. Сервер поддержки: https://support-production-c039.up.railway.app
Если сервер недоступен — напишите нам об этом в Telegram-канале.
Попробуйте выйти из профиля и зайти снова (создастся новый clientId).

--- 30.0 Другая проблема / общий чеклист ---
1. Перезапустите приложение
2. Проверьте интернет
3. Проверьте логи: %appdata%\JARVIS\JarvisV2\logs\jarvis.log
4. Проверьте, что версия актуальная (сейчас 3.0)
5. Сбросьте config.json (%appdata%\JARVIS\JarvisV2\config.json)
6. Переустановите приложение
7. Если ничего не помогло — напишите в Telegram-канал @Jarvis_free с приложенным логом
 Если проблема описана не полностью — предложи уточнить. "
    "Не используй маркдаун. Ответ должен быть не длиннее 300 символов."
)

@app.route("/api/conversations/<client_id>/suggest", methods=["POST"])
def suggest_reply(client_id):
    auth_err = _check_auth_or_403()
    if auth_err: return auth_err
    data = _load()
    conv = data.get("conversations", {}).get(client_id, {})
    msgs = conv.get("messages", []) if isinstance(conv, dict) else (conv if isinstance(conv, list) else [])
    if not msgs:
        return jsonify({"suggestion": "", "ok": True})

    history = ""
    for m in msgs:
        role = "Пользователь" if m.get("role") == "user" else "Поддержка"
        history += f"{role}: {m.get('text', '')}\n"

    try:
        r = http.post(AI_URL, json={
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": history.strip()},
            ]
        }, headers={
            "Authorization": f"Bearer {AI_KEY}",
            "Content-Type": "application/json"
        }, timeout=15)
        r.raise_for_status()
        j = r.json()
        suggestion = j.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return jsonify({"error": str(e), "suggestion": "", "ok": False}), 500

    return jsonify({"suggestion": suggestion.strip(), "ok": True})

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
