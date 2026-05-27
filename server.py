#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http import cookies
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("ART_DATA_DIR", ROOT / "data")).resolve()
IMAGE_DIR = Path(os.environ.get("ART_IMAGE_DIR", DATA_DIR / "images")).resolve()
DB_PATH = Path(os.environ.get("ART_DB_PATH", DATA_DIR / "art.db")).resolve()
SESSION_TTL = int(os.environ.get("ART_SESSION_TTL_SECONDS", "604800"))
MAX_REFERENCE_IMAGES = int(os.environ.get("ART_MAX_REFERENCE_IMAGES", "9"))
MAX_PROMPT_LEN = int(os.environ.get("ART_MAX_PROMPT_LENGTH", "1600"))


STYLES = {
    "photography": "professional photographic image, refined lighting, natural lens depth, editorial color grading",
    "illustration": "premium digital illustration, clean shapes, expressive composition, polished detail",
    "poster": "high-impact poster design, strong hierarchy, dramatic composition, print-ready visual clarity",
    "brand": "brand campaign visual, art-directed, coherent identity system, premium commercial finish",
    "product": "product hero image, crisp material detail, controlled studio lighting, sales-ready composition",
    "concept": "concept design sheet, imaginative but coherent forms, cinematic environment thinking",
    "character": "character design, distinctive silhouette, costume detail, expressive pose, production art quality",
    "advertising": "commercial advertising image, memorable focal point, polished retouching, aspirational tone",
}

RATIO_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1536x864",
    "9:16": "864x1536",
    "4:3": "1344x1008",
    "3:4": "1008x1344",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "4:5": "1024x1280",
    "21:9": "1536x640",
}

QUALITY_DEFAULTS = {"low": "low", "medium": "standard", "high": "hd", "auto": "auto", "draft": "standard", "standard": "standard", "ultra": "hd"}
RESOLUTION_SIZES = {
    "1k": {"1:1": "1024x1024", "16:9": "1536x864", "9:16": "864x1536", "4:3": "1344x1008", "3:4": "1008x1344", "3:2": "1536x1024", "2:3": "1024x1536"},
    "2k": {"1:1": "2048x2048", "16:9": "2048x1152", "9:16": "1152x2048", "4:3": "2048x1536", "3:4": "1536x2048", "3:2": "2048x1360", "2:3": "1360x2048"},
    "4k": {"1:1": "2880x2880", "16:9": "3840x2160", "9:16": "2160x3840", "4:3": "3840x2880", "3:4": "2880x3840", "3:2": "3840x2560", "2:3": "2560x3840"},
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2_sha256$200000${salt}${base64.b64encode(digest).decode()}"


def verify_password(password, stored):
    try:
        algo, rounds, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(base64.b64encode(calc).decode(), digest)
    except Exception:
        return False


def crypto_key():
    raw = os.environ.get("ART_SECRET_KEY") or "dev-secret-change-me"
    return hashlib.sha256(raw.encode()).digest()


def xor_crypt(text):
    if not text:
        return ""
    data = text.encode()
    key = crypto_key()
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    mac = hmac.new(key, out, hashlib.sha256).hexdigest()[:16]
    return "v1:" + mac + ":" + base64.urlsafe_b64encode(out).decode()


def xor_decrypt(value):
    if not value:
        return ""
    try:
        prefix, mac, payload = value.split(":", 2)
        if prefix != "v1":
            return ""
        key = crypto_key()
        raw = base64.urlsafe_b64decode(payload.encode())
        expected = hmac.new(key, raw, hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(mac, expected):
            return ""
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode()
    except Exception:
        return ""


def public_provider(row, reveal_key=False):
    d = dict(row)
    key = xor_decrypt(d.pop("api_key_enc", "") or "")
    d["api_key"] = key if reveal_key else ("••••••••" + key[-4:] if key else "")
    d["models"] = json.loads(d.get("models_json") or "[]")
    d.pop("models_json", None)
    return d


def resolve_provider_api_key(data):
    raw = data.get("api_key") or ""
    if raw and not str(raw).startswith("••••"):
        return str(raw)
    if not data.get("id"):
        return ""
    with db() as conn:
        row = conn.execute("SELECT api_key_enc FROM providers WHERE id=?", (data["id"],)).fetchone()
    return xor_decrypt(row["api_key_enc"]) if row else ""


def init_db():
    ensure_dirs()
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_codes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT UNIQUE NOT NULL,
              label TEXT DEFAULT '',
              note TEXT DEFAULT '',
              active INTEGER DEFAULT 1,
              total_quota INTEGER NOT NULL,
              used_quota INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              last_used_at TEXT
            );
            CREATE TABLE IF NOT EXISTS providers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              base_url TEXT NOT NULL,
              api_key_enc TEXT DEFAULT '',
              models_json TEXT NOT NULL DEFAULT '[]',
              default_model TEXT DEFAULT '',
              priority INTEGER DEFAULT 100,
              is_default INTEGER DEFAULT 0,
              active INTEGER DEFAULT 1,
              archived INTEGER DEFAULT 0,
              supports_reference INTEGER DEFAULT 0,
              call_count INTEGER DEFAULT 0,
              fail_count INTEGER DEFAULT 0,
              last_called_at TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              subject_id INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS generations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              access_code_id INTEGER,
              provider_id INTEGER,
              original_prompt TEXT NOT NULL,
              enhanced_prompt TEXT NOT NULL,
              negative_prompt TEXT DEFAULT '',
              style TEXT DEFAULT '',
              ratio TEXT DEFAULT '',
              quality TEXT DEFAULT '',
              size TEXT DEFAULT '',
              provider_name TEXT DEFAULT '',
              model TEXT DEFAULT '',
              status TEXT NOT NULL,
              error TEXT DEFAULT '',
              image_path TEXT DEFAULT '',
              image_url TEXT DEFAULT '',
              params_json TEXT DEFAULT '{}',
              created_at TEXT NOT NULL,
              FOREIGN KEY(access_code_id) REFERENCES access_codes(id) ON DELETE SET NULL,
              FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE SET NULL
            );
            """
        )
        if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO admins(username,password_hash,created_at) VALUES(?,?,?)",
                (
                    os.environ.get("ART_ADMIN_USER", "admin"),
                    hash_password(os.environ.get("ART_ADMIN_PASSWORD", "ChangeMe123!")),
                    now_iso(),
                ),
            )
        if conn.execute("SELECT COUNT(*) FROM access_codes").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO access_codes(code,label,note,total_quota,created_at) VALUES(?,?,?,?,?)",
                (os.environ.get("ART_DEFAULT_ACCESS_CODE", "PRIVATE-STUDIO"), "Default Studio Pass", "Created on first boot", 50, now_iso()),
            )


def create_session(kind, subject_id):
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions(token,kind,subject_id,expires_at,created_at) VALUES(?,?,?,?,?)",
            (token, kind, subject_id, int(time.time()) + SESSION_TTL, now_iso()),
        )
    return token


def parse_cookie(header):
    jar = cookies.SimpleCookie()
    if header:
        jar.load(header)
    return {k: v.value for k, v in jar.items()}


def session_subject(token, kind):
    if not token:
        return None
    with db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token=? AND kind=? AND expires_at>?", (token, kind, int(time.time()))).fetchone()
        return row["subject_id"] if row else None


def validate_access(code_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM access_codes WHERE id=?", (code_id,)).fetchone()
        if not row:
            return None, "访问会话无效，请重新输入访问凭证。"
        if not row["active"]:
            return None, "该访问凭证已停用。"
        if row["used_quota"] >= row["total_quota"]:
            return None, "该访问凭证额度已用尽。"
        return row, None


def build_prompt(prompt, style):
    style_hint = STYLES.get(style, "")
    return f"{prompt.strip()}\n\nCreative direction: {style_hint}" if style_hint else prompt.strip()


def append_negative_prompt(prompt, negative_prompt):
    negative = (negative_prompt or "").strip()
    return f"{prompt} --no {negative}" if negative else prompt


def build_generation_payload(params):
    prompt = (params.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("请输入主提示词。")
    if len(prompt) > MAX_PROMPT_LEN:
        raise ValueError(f"提示词过长，请控制在 {MAX_PROMPT_LEN} 字以内。")
    ratio = params.get("ratio") or "1:1"
    resolution = str(params.get("resolution") or "1k").lower()
    size = params.get("size") or RESOLUTION_SIZES.get(resolution, RESOLUTION_SIZES["1k"]).get(ratio, RATIO_SIZES.get(ratio, "1024x1024"))
    quality = params.get("quality") or "medium"
    negative_prompt = (params.get("negative_prompt") or "").strip()
    enhanced_prompt = build_prompt(prompt, params.get("style") or "")
    return {
        "prompt": append_negative_prompt(enhanced_prompt, negative_prompt),
        "negative_prompt": negative_prompt,
        "model": params.get("model") or "",
        "n": 1,
        "size": size,
        "quality": QUALITY_DEFAULTS.get(quality, "standard"),
        "response_format": "b64_json",
    }


def parse_models_response(data):
    if isinstance(data, dict):
        items = data.get("data") or data.get("models") or data.get("result") or []
    else:
        items = data
    return normalize_provider_models(items)


def normalize_provider_models(models):
    normalized = []
    seen = set()
    for item in models or []:
        if isinstance(item, str):
            mid = item.strip()
            name = mid
            enabled = False
            supports_reference = False
        elif isinstance(item, dict):
            mid = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
            name = str(item.get("name") or mid).strip()
            enabled = bool(item.get("enabled"))
            supports_reference = bool(item.get("supports_reference", item.get("multimodal", False)))
        else:
            continue
        if not mid or mid in seen:
            continue
        seen.add(mid)
        normalized.append({"id": mid, "name": name or mid, "enabled": enabled, "supports_reference": supports_reference})
    return normalized


def provider_supports_model(provider, model, needs_reference=False):
    models = json.loads(provider["models_json"] or "[]")
    for m in models:
        if m.get("enabled") and m.get("id") == model:
            return (not needs_reference) or bool(m.get("supports_reference") or provider["supports_reference"])
    return False


def default_model(needs_reference=False):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM providers WHERE active=1 AND archived=0 ORDER BY is_default DESC, priority ASC, id ASC"
        ).fetchall()
    for provider in rows:
        for model in json.loads(provider["models_json"] or "[]"):
            if model.get("enabled") and ((not needs_reference) or model.get("supports_reference") or provider["supports_reference"]):
                return model.get("id") or provider["default_model"]
    return ""


def select_providers(model, needs_reference=False):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM providers WHERE active=1 AND archived=0 ORDER BY is_default DESC, priority ASC, id ASC"
        ).fetchall()
    return [r for r in rows if provider_supports_model(r, model, needs_reference)]


def extract_image_from_response(data):
    if isinstance(data, dict):
        if data.get("b64_json"):
            return ("base64", data["b64_json"])
        if data.get("url"):
            return ("url", data["url"])
        if "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                found = extract_image_from_response(item)
                if found:
                    return found
        choices = data.get("choices") or []
        for ch in choices:
            msg = ch.get("message", {}) if isinstance(ch, dict) else {}
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") in ("image_url", "input_image") and isinstance(part.get("image_url"), dict):
                            return ("url", part["image_url"].get("url", ""))
                        found = extract_image_from_response(part)
                        if found:
                            return found
            if isinstance(content, str):
                found = extract_image_from_text(content)
                if found:
                    return found
        for v in data.values():
            if isinstance(v, (dict, list)):
                found = extract_image_from_response(v)
                if found:
                    return found
    if isinstance(data, list):
        for item in data:
            found = extract_image_from_response(item)
            if found:
                return found
    return None


def extract_image_from_text(text):
    for token in text.replace("\n", " ").split():
        if token.startswith("data:image/"):
            return ("data_url", token)
        if token.startswith("http://") or token.startswith("https://"):
            clean = token.strip("),'\"")
            if any(ext in clean.lower() for ext in [".png", ".jpg", ".jpeg", ".webp"]):
                return ("url", clean)
    return None


def save_image(kind, value):
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:10]}.png"
    path = IMAGE_DIR / filename
    if kind == "base64":
        path.write_bytes(base64.b64decode(value.split(",", 1)[-1]))
    elif kind == "data_url":
        path.write_bytes(base64.b64decode(value.split(",", 1)[1]))
    elif kind == "url":
        with urllib.request.urlopen(value, timeout=30) as resp:
            path.write_bytes(resp.read())
    else:
        raise ValueError("无法识别图片返回格式。")
    return str(path), f"/images/{filename}"


def write_mock_image(prompt, ratio):
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:10]}.svg"
    path = IMAGE_DIR / filename
    safe = prompt[:220].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    w, h = (1024, 1024)
    if ratio in RATIO_SIZES:
        w, h = [int(x) for x in RATIO_SIZES[ratio].split("x")]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#111827"/><stop offset=".52" stop-color="#22577a"/><stop offset="1" stop-color="#f4b860"/></linearGradient></defs>
<rect width="100%" height="100%" fill="url(#g)"/><circle cx="{w*.78}" cy="{h*.22}" r="{min(w,h)*.16}" fill="#f7fff7" opacity=".18"/>
<rect x="{w*.08}" y="{h*.1}" width="{w*.84}" height="{h*.78}" rx="28" fill="#0b1220" opacity=".32" stroke="#ffffff" stroke-opacity=".28"/>
<text x="{w*.12}" y="{h*.22}" fill="#fff" font-family="Arial, sans-serif" font-size="{max(30, min(w,h)//18)}" font-weight="700">Private AI Studio</text>
<foreignObject x="{w*.12}" y="{h*.3}" width="{w*.76}" height="{h*.42}"><div xmlns="http://www.w3.org/1999/xhtml" style="font: {max(20, min(w,h)//32)}px Arial; color:#eef6ff; line-height:1.45;">{safe}</div></foreignObject>
<text x="{w*.12}" y="{h*.82}" fill="#dbeafe" font-family="Arial, sans-serif" font-size="{max(18, min(w,h)//42)}">Mock render · replace Provider to generate real images</text>
</svg>"""
    path.write_text(svg)
    return str(path), f"/images/{filename}"


def call_provider(provider, payload, references):
    with db() as conn:
        conn.execute("UPDATE providers SET call_count=call_count+1,last_called_at=? WHERE id=?", (now_iso(), provider["id"]))
    if provider["base_url"].startswith("mock://"):
        time.sleep(0.8)
        return write_mock_image(payload["prompt"], payload.get("ratio", "1:1"))
    api_key = xor_decrypt(provider["api_key_enc"])
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = dict(payload)
    if references:
        body["reference_images"] = references
    url = provider["base_url"].rstrip("/")
    endpoint = url if url.endswith(("/images/generations", "/chat/completions")) else url + "/images/generations"
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    image = extract_image_from_response(data)
    if not image or not image[1]:
        raise ValueError("Provider 已返回结果，但未解析到图片。")
    return save_image(image[0], image[1])


class Handler(BaseHTTPRequestHandler):
    server_version = "PrivateAIStudio/1.0"

    def log_message(self, fmt, *args):
        return

    def send_json(self, data, status=200, set_cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 20_000_000:
            raise ValueError("请求体过大。")
        return json.loads(self.rfile.read(length).decode() or "{}")

    def cookie_token(self, name):
        return parse_cookie(self.headers.get("Cookie")).get(name)

    def user_id(self):
        return session_subject(self.cookie_token("studio_session"), "user")

    def admin_id(self):
        return session_subject(self.cookie_token("admin_session"), "admin")

    def require_user(self):
        uid = self.user_id()
        if not uid:
            self.send_json({"error": "请先输入有效访问凭证。"}, 401)
            return None
        row, err = validate_access(uid)
        if err:
            self.send_json({"error": err}, 403)
            return None
        return row

    def require_admin(self):
        aid = self.admin_id()
        if not aid:
            self.send_json({"error": "请先登录管理员后台。"}, 401)
            return None
        return aid

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self.handle_api_get(path)
        if path.startswith("/images/"):
            return self.serve_file(IMAGE_DIR / path.removeprefix("/images/"))
        target = STATIC_DIR / ("index.html" if path in ("/", "/app", "/admin") else path.lstrip("/"))
        return self.serve_file(target)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            return self.handle_api_post(path)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception:
            return self.send_json({"error": "服务器处理失败，请稍后重试或联系管理员。"}, 500)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if not self.require_admin():
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "admin"]:
            table = {"codes": "access_codes", "providers": "providers"}.get(parts[2])
            if table:
                with db() as conn:
                    if table == "providers":
                        conn.execute("UPDATE providers SET archived=1, active=0 WHERE id=?", (parts[3],))
                    else:
                        conn.execute(f"DELETE FROM {table} WHERE id=?", (parts[3],))
                return self.send_json({"ok": True})
        self.send_json({"error": "接口不存在。"}, 404)

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            path = STATIC_DIR / "index.html"
        ctype = "text/html"
        if path.suffix == ".css":
            ctype = "text/css"
        elif path.suffix == ".js":
            ctype = "application/javascript"
        elif path.suffix == ".svg":
            ctype = "image/svg+xml"
        elif path.suffix in (".png", ".jpg", ".jpeg", ".webp"):
            ctype = "image/" + path.suffix.lstrip(".").replace("jpg", "jpeg")
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_api_get(self, path):
        if path == "/api/me":
            uid = self.user_id()
            if not uid:
                return self.send_json({"authenticated": False})
            with db() as conn:
                code = conn.execute("SELECT * FROM access_codes WHERE id=?", (uid,)).fetchone()
            return self.send_json({"authenticated": True, "code": self.code_public(code)})
        if path == "/api/config":
            with db() as conn:
                rows = conn.execute("SELECT * FROM providers WHERE active=1 AND archived=0 ORDER BY is_default DESC, priority ASC, id ASC").fetchall()
            models = []
            seen = set()
            for p in rows:
                for m in json.loads(p["models_json"] or "[]"):
                    if m.get("enabled") and m.get("id") not in seen:
                        seen.add(m["id"])
                        models.append({"id": m["id"], "name": m.get("name") or m["id"], "supports_reference": bool(m.get("supports_reference") or p["supports_reference"])})
            return self.send_json({"styles": list(STYLES.keys()), "ratios": list(RATIO_SIZES.keys()), "models": models, "maxReferences": MAX_REFERENCE_IMAGES})
        if path == "/api/history":
            code = self.require_user()
            if not code:
                return
            with db() as conn:
                rows = conn.execute("SELECT * FROM generations WHERE access_code_id=? ORDER BY id DESC LIMIT 60", (code["id"],)).fetchall()
            return self.send_json({"items": [dict(r) for r in rows]})
        if path.startswith("/api/admin/"):
            if not self.require_admin():
                return
            return self.admin_get(path)
        self.send_json({"error": "接口不存在。"}, 404)

    def handle_api_post(self, path):
        data = self.read_json()
        if path == "/api/login":
            code = (data.get("code") or "").strip()
            with db() as conn:
                row = conn.execute("SELECT * FROM access_codes WHERE code=?", (code,)).fetchone()
            if not row:
                return self.send_json({"error": "访问凭证不存在。"}, 401)
            if not row["active"] or row["used_quota"] >= row["total_quota"]:
                return self.send_json({"error": "访问凭证不可用或额度已用尽。"}, 403)
            token = create_session("user", row["id"])
            return self.send_json({"ok": True, "code": self.code_public(row)}, set_cookie=f"studio_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}")
        if path == "/api/logout":
            return self.send_json({"ok": True}, set_cookie="studio_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        if path == "/api/generate":
            return self.generate(data)
        if path == "/api/admin/login":
            username = (data.get("username") or "").strip()
            password = data.get("password") or ""
            with db() as conn:
                row = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                return self.send_json({"error": "管理员账号或密码错误。"}, 401)
            token = create_session("admin", row["id"])
            return self.send_json({"ok": True}, set_cookie=f"admin_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}")
        if path == "/api/admin/logout":
            return self.send_json({"ok": True}, set_cookie="admin_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        if path.startswith("/api/admin/"):
            if not self.require_admin():
                return
            return self.admin_post(path, data)
        self.send_json({"error": "接口不存在。"}, 404)

    def code_public(self, row):
        return {
            "id": row["id"], "code": row["code"], "label": row["label"], "active": bool(row["active"]),
            "total_quota": row["total_quota"], "used_quota": row["used_quota"],
            "remaining": max(0, row["total_quota"] - row["used_quota"]), "last_used_at": row["last_used_at"],
        }

    def generate(self, data):
        code = self.require_user()
        if not code:
            return
        refs = data.get("references") or []
        if len(refs) > MAX_REFERENCE_IMAGES:
            return self.send_json({"error": f"最多上传 {MAX_REFERENCE_IMAGES} 张参考图。"}, 400)
        payload = build_generation_payload(data)
        model = payload["model"] or default_model(bool(refs))
        if not model:
            return self.send_json({"error": "后台还没有配置可用模型，请联系管理员。"}, 400)
        payload["model"] = model
        providers = select_providers(model, bool(refs))
        if not providers:
            return self.send_json({"error": "当前模型没有匹配的可用 Provider，或该模型不支持参考图。"}, 400)
        gen_id = None
        params_json = json.dumps({k: data.get(k) for k in ["prompt", "negative_prompt", "style", "ratio", "quality", "size", "model"]}, ensure_ascii=False)
        with db() as conn:
            cur = conn.execute(
                """INSERT INTO generations(access_code_id,original_prompt,enhanced_prompt,negative_prompt,style,ratio,quality,size,model,status,params_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (code["id"], data.get("prompt", ""), payload["prompt"], payload["negative_prompt"], data.get("style", ""), data.get("ratio", "1:1"), data.get("quality", "standard"), payload["size"], model, "running", params_json, now_iso()),
            )
            gen_id = cur.lastrowid
        errors = []
        for p in providers:
            try:
                path, url = call_provider(p, dict(payload, ratio=data.get("ratio", "1:1")), refs)
                with db() as conn:
                    conn.execute("UPDATE access_codes SET used_quota=used_quota+1,last_used_at=? WHERE id=?", (now_iso(), code["id"]))
                    conn.execute(
                        "UPDATE generations SET provider_id=?,provider_name=?,status='success',image_path=?,image_url=?,model=? WHERE id=?",
                        (p["id"], p["name"], path, url, model, gen_id),
                    )
                return self.send_json({"ok": True, "id": gen_id, "image_url": url, "provider": p["name"], "model": model})
            except Exception as e:
                errors.append(f"{p['name']}: {str(e)}")
                with db() as conn:
                    conn.execute("UPDATE providers SET fail_count=fail_count+1 WHERE id=?", (p["id"],))
        message = "所有可用 Provider 都生成失败：" + "；".join(errors[-3:])
        with db() as conn:
            conn.execute("UPDATE generations SET status='failed',error=? WHERE id=?", (message, gen_id))
        return self.send_json({"error": message, "can_retry_with_other_model": True}, 502)

    def admin_get(self, path):
        with db() as conn:
            if path == "/api/admin/me":
                return self.send_json({"authenticated": True})
            if path == "/api/admin/stats":
                today = datetime.now().strftime("%Y-%m-%d")
                stats = {
                    "codes": conn.execute("SELECT COUNT(*) FROM access_codes").fetchone()[0],
                    "success": conn.execute("SELECT COUNT(*) FROM generations WHERE status='success'").fetchone()[0],
                    "today": conn.execute("SELECT COUNT(*) FROM generations WHERE created_at LIKE ?", (today + "%",)).fetchone()[0],
                    "providers": conn.execute("SELECT COUNT(*) FROM providers WHERE archived=0").fetchone()[0],
                    "failed": conn.execute("SELECT COUNT(*) FROM generations WHERE status='failed'").fetchone()[0],
                }
                return self.send_json(stats)
            if path == "/api/admin/codes":
                rows = conn.execute("SELECT * FROM access_codes ORDER BY id DESC").fetchall()
                return self.send_json({"items": [dict(r, remaining=max(0, r["total_quota"] - r["used_quota"])) for r in rows]})
            if path == "/api/admin/providers":
                rows = conn.execute("SELECT * FROM providers WHERE archived=0 ORDER BY is_default DESC, priority ASC, id ASC").fetchall()
                return self.send_json({"items": [public_provider(r) for r in rows]})
            if path == "/api/admin/generations":
                rows = conn.execute(
                    """SELECT g.*, c.code AS access_code, c.label AS access_label
                       FROM generations g LEFT JOIN access_codes c ON c.id=g.access_code_id
                       ORDER BY g.id DESC LIMIT 200"""
                ).fetchall()
                return self.send_json({"items": [dict(r) for r in rows]})
        self.send_json({"error": "接口不存在。"}, 404)

    def admin_post(self, path, data):
        if path == "/api/admin/codes":
            return self.save_code(data)
        if path == "/api/admin/providers":
            return self.save_provider(data)
        if path == "/api/admin/providers/test":
            return self.test_provider(data)
        if path == "/api/admin/providers/models":
            return self.fetch_models(data)
        self.send_json({"error": "接口不存在。"}, 404)

    def save_code(self, data):
        code = (data.get("code") or "").strip()
        total = int(data.get("total_quota") or 0)
        used = int(data.get("used_quota") or 0)
        if not code:
            return self.send_json({"error": "访问凭证不能为空。"}, 400)
        if total < 0 or used < 0 or used > total:
            return self.send_json({"error": "额度设置不合法，已用额度不能大于总额度。"}, 400)
        with db() as conn:
            try:
                if data.get("id"):
                    conn.execute(
                        "UPDATE access_codes SET code=?,label=?,note=?,active=?,total_quota=?,used_quota=? WHERE id=?",
                        (code, data.get("label", ""), data.get("note", ""), int(bool(data.get("active", True))), total, used, data["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO access_codes(code,label,note,active,total_quota,used_quota,created_at) VALUES(?,?,?,?,?,?,?)",
                        (code, data.get("label", ""), data.get("note", ""), int(bool(data.get("active", True))), total, used, now_iso()),
                    )
            except sqlite3.IntegrityError:
                return self.send_json({"error": "访问凭证重复，请换一个。"}, 400)
        return self.send_json({"ok": True})

    def save_provider(self, data):
        name = (data.get("name") or "").strip()
        base = (data.get("base_url") or "").strip()
        models = normalize_provider_models(data.get("models") or [])
        if not name or not base:
            return self.send_json({"error": "Provider 名称和 Base URL 不能为空。"}, 400)
        enabled_models = [m for m in models if m.get("enabled")]
        if not enabled_models:
            return self.send_json({"error": "请至少启用一个模型。"}, 400)
        enabled_ids = {m["id"] for m in enabled_models}
        default_model = data.get("default_model") if data.get("default_model") in enabled_ids else enabled_models[0]["id"]
        with db() as conn:
            if data.get("is_default"):
                conn.execute("UPDATE providers SET is_default=0")
            api_key_sql = ""
            args = []
            if data.get("api_key") and not str(data.get("api_key")).startswith("••••"):
                api_key_sql = ", api_key_enc=?"
                args.append(xor_crypt(data.get("api_key")))
            if data.get("id"):
                args = [name, base, json.dumps(models), default_model, int(data.get("priority") or 100), int(bool(data.get("is_default"))), int(bool(data.get("active", True))), 1] + args + [data["id"]]
                conn.execute(
                    f"UPDATE providers SET name=?,base_url=?,models_json=?,default_model=?,priority=?,is_default=?,active=?,supports_reference=?{api_key_sql} WHERE id=?",
                    args,
                )
            else:
                conn.execute(
                    """INSERT INTO providers(name,base_url,api_key_enc,models_json,default_model,priority,is_default,active,supports_reference,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (name, base, xor_crypt(data.get("api_key", "")), json.dumps(models), default_model, int(data.get("priority") or 100), int(bool(data.get("is_default"))), int(bool(data.get("active", True))), 1, now_iso()),
                )
        return self.send_json({"ok": True})

    def test_provider(self, data):
        base = (data.get("base_url") or "").strip()
        api_key = resolve_provider_api_key(data)
        if base.startswith("mock://"):
            return self.send_json({"ok": True, "message": "Mock Provider 可用。"})
        try:
            req = urllib.request.Request(base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return self.send_json({"ok": True, "message": f"连接成功，状态 {resp.status}。"})
        except Exception as e:
            return self.send_json({"ok": False, "message": f"连接失败：{str(e)}"}, 400)

    def fetch_models(self, data):
        base = (data.get("base_url") or "").strip()
        api_key = resolve_provider_api_key(data)
        if base.startswith("mock://"):
            return self.send_json({"models": [{"id": "mock-vision-xl", "name": "Vision XL Mock", "enabled": False, "supports_reference": True}]})
        try:
            req = urllib.request.Request(base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
            with urllib.request.urlopen(req, timeout=20) as resp:
                models = parse_models_response(json.loads(resp.read().decode()))
            return self.send_json({"models": models})
        except Exception as e:
            return self.send_json({"error": f"拉取模型失败：{str(e)}"}, 400)


def main():
    init_db()
    host = os.environ.get("ART_HOST", "127.0.0.1")
    port = int(os.environ.get("ART_PORT", "8080"))
    print(f"Private AI Studio listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
