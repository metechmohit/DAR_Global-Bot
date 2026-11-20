"""WSGI routes shared by the local server and the production Waitress process."""
import csv
import io
import json
import logging
import mimetypes
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from http import HTTPStatus
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit, parse_qs
from wsgiref.simple_server import WSGIServer, make_server
from .config import ROOT, PROCESSED, DB
from . import openrouter
from .chat import answer
from .search import search_records, get_records

LOG = logging.getLogger("server")
_requests = OrderedDict()
_rate_lock = threading.Lock()
_model_slots = threading.BoundedSemaphore(3)
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
STATIC = {"/": "index.html", "/app.js": "app.js", "/history.js": "history.js", "/style.css": "style.css", "/favicon.svg": "favicon.svg"}


def response(status, body, content_type="application/json; charset=utf-8", extra=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False).encode()
    elif isinstance(body, str):
        body = body.encode()
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body))),
               ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
               ("Cache-Control", "no-store" if "json" in content_type else "no-cache"),
               ("Content-Security-Policy", CSP)]
    headers.extend((extra or {}).items())
    return status, headers, body


def index_ready():
    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3) as con:
            return con.execute("SELECT count(*) FROM records").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def _export(name):
    if os.getenv("ATLAS_DEV_TOOLS", "0") != "1":
        return response(404, {"error": "Not found"})
    if name not in ("records.csv", "darglobal.csv", "wasalt.csv", "failures.csv"):
        return response(404, {"error": "Export not found"})
    file = PROCESSED / name
    if not file.exists():
        return response(404, {"error": "Export not found"})
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    with file.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            writer.writerow(["'" + cell if cell.lstrip().startswith(("=", "+", "-", "@")) else cell for cell in row])
    return response(200, "\ufeff" + out.getvalue(), "text/csv; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="{name}"'})


def _dispatch(env):
    method = env.get("REQUEST_METHOD", "GET")
    path = env.get("PATH_INFO", "/")
    host = env.get("HTTP_HOST", "")
    if os.getenv("APP_ENV", "development") != "production":
        try:
            if urlsplit("//" + host).hostname not in ("127.0.0.1", "localhost", "::1"):
                return response(403, {"error": "Unexpected Host header"})
        except ValueError:
            return response(400, {"error": "Invalid Host header"})
    if method in ("GET", "HEAD"):
        if path == "/healthz":
            ready = index_ready()
            return response(200 if ready else 503, {"status": "ok" if ready else "unavailable"})
        if path == "/api/status":
            file = PROCESSED / "stats.json"
            stats = json.loads(file.read_text()) if file.exists() else {}
            payload = {"ready": index_ready(), "stats": {"by_city": stats.get("by_city", {})}}
            if os.getenv("ATLAS_DEV_TOOLS", "0") == "1":
                payload.update(stats=stats, ai_configured=openrouter.configured(), model=os.getenv("OPENROUTER_MODEL", "openrouter/free"))
            return response(200, payload)
        if path == "/api/search":
            params = {key: values[0] for key, values in parse_qs(env.get("QUERY_STRING", "")).items()}
            limit = int(params.pop("limit", "12"))
            offset = int(params.pop("offset", "0"))
            return response(200, search_records(params, limit, offset))
        if path.startswith("/api/records/"):
            rid = path.rsplit("/", 1)[-1]
            records = get_records([rid]) if re.fullmatch(r"[a-f0-9]{24}", rid) else []
            return response(200 if records else 404, records[0] if records else {"error": "Record not found"})
        if path.startswith("/api/export/"):
            return _export(path.rsplit("/", 1)[-1])
        if path in STATIC:
            file = ROOT / "static" / STATIC[path]
            mime = mimetypes.guess_type(str(file))[0] or "text/plain"
            return response(200, file.read_bytes(), mime + "; charset=utf-8")
        return response(404, {"error": "Not found"})
    if method != "POST":
        return response(405, {"error": "Method not allowed"}, extra={"Allow": "GET, HEAD, POST"})
    if path != "/api/chat":
        return response(404, {"error": "Not found"})
    origin = env.get("HTTP_ORIGIN")
    if origin and urlsplit(origin).netloc != host:
        return response(403, {"error": "Cross-origin requests are not permitted"})
    if not env.get("CONTENT_TYPE", "").startswith("application/json"):
        return response(415, {"error": "Send application/json"})
    with _rate_lock:
        current = time.monotonic()
        client = env.get("REMOTE_ADDR", "unknown")
        events = _requests.setdefault(client, deque())
        _requests.move_to_end(client)
        while events and current - events[0] > 60:
            events.popleft()
        if len(events) >= 12:
            return response(429, {"error": "Please wait a moment before sending more questions."}, extra={"Retry-After": "60"})
        events.append(current)
        if len(_requests) > 4096:
            _requests.popitem(last=False)
    size = int(env.get("CONTENT_LENGTH") or "0")
    if not 0 < size <= 24000:
        return response(413, {"error": "Request is too large"})
    data = json.loads(env["wsgi.input"].read(size))
    if not isinstance(data, dict):
        return response(400, {"error": "Invalid JSON request"})
    question = data.get("message", "")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1800:
        return response(400, {"error": "Enter a question between 1 and 1,800 characters"})
    history, ids = data.get("history", []), data.get("compare_ids", [])
    if not isinstance(history, list) or not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(i, str) or not re.fullmatch(r"[a-f0-9]{24}", i) for i in ids):
        return response(400, {"error": "Invalid chat context"})
    if not _model_slots.acquire(blocking=False):
        return response(429, {"error": "The assistant is busy. Please try again shortly."})
    try:
        result = answer(question.strip(), history=history, previous_filters=data.get("filters"), compare_ids=ids,
                        use_ai=data.get("use_ai") is not False)
        if result.get("notice"):
            LOG.warning("Chat fallback: %s", result["notice"])
        # Provider details belong in server logs, not the public response.
        result.pop("model", None)
        if result.get("notice"):
            result["notice"] = "temporarily_unavailable"
        return response(200, result)
    finally:
        _model_slots.release()


def application(environ, start_response):
    try:
        status, headers, body = _dispatch(environ)
    except (ValueError, TypeError, UnicodeError):
        status, headers, body = response(400, {"error": "Invalid request parameters or JSON"})
    except Exception:
        LOG.exception("Request failed")
        status, headers, body = response(500, {"error": "Unable to complete this request. Please try again shortly."})
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    return [b"" if environ.get("REQUEST_METHOD") == "HEAD" else body]


def serve(host=None, port=None, production=False):
    if production:
        os.environ["APP_ENV"] = "production"
    from .ingest import build
    from .config import RAW
    if not DB.exists() or any(p.stat().st_mtime > DB.stat().st_mtime for p in RAW.glob("*.csv")):
        build()
    if not index_ready():
        raise SystemExit("The search index is empty or invalid. Run python -m app ingest.")
    if os.getenv("REQUIRE_API_KEY", "0") == "1" and not openrouter.configured():
        raise SystemExit("OPENROUTER_API_KEY is required for this deployment. Set it as a runtime secret.")
    host = host or os.getenv("HOST", "127.0.0.1")
    port = port or int(os.getenv("PORT", "8000"))
    if production:
        try:
            from waitress import serve as run_server
        except ImportError:
            raise SystemExit("Install production requirements inside .venv: .venv/bin/python -m pip install -r requirements.txt") from None
        print(f"Atlas production server listening on {host}:{port}", flush=True)
        run_server(application, host=host, port=port, threads=4, channel_timeout=150,
                   max_request_body_size=24000, clear_untrusted_proxy_headers=True)
        return
    class LocalServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True
    try:
        server = make_server(host, port, application, server_class=LocalServer)
    except PermissionError:
        raise SystemExit("Run the server from your regular terminal; this process cannot open a local port.") from None
    except OSError as exc:
        raise SystemExit(f"Cannot bind {host}:{port}: {exc}. Try --port 8001.") from None
    print(f"\nProperty Atlas is running at http://{host}:{port}\nPress Ctrl+C to stop.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
