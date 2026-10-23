"""The phone link: a tiny receiver on YOUR network that phones, watches and automations can POST small JSON events to
("heart_rate", "notification", "call", "app_usage" …). Off by default. Only devices on your private network can use it,
only with the secret token, only these event types, and only small messages."""
import hmac
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .hands.net import is_private

MAX_BODY = 65536                                # one Health Connect batch can hold a few hours of readings
MAX_AGE = 6 * 3600                              # readings older than this are ignored
KINDS = {"ping", "heart_rate", "spo2", "steps", "notification", "call", "app_usage"}


def _text(v, n, name, required=False):
    if v is None or v == "":
        if required:
            raise ValueError(f"{name} is required")
        return ""
    if not isinstance(v, str):
        raise ValueError(f"{name} must be text")
    return "".join(ch for ch in v if ch >= " " or ch in "\n")[:n].strip()


def _num(v, lo, hi, name):
    if isinstance(v, bool):
        raise ValueError(f"{name} must be a number")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if not lo <= f <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return f


def validate(ev):
    """A phone's JSON → a clean event, or ValueError saying what is wrong. Nothing else gets through."""
    if not isinstance(ev, dict):
        raise ValueError("send a JSON object")
    kind = ev.get("type")
    if kind not in KINDS:
        raise ValueError("unknown type; use one of: " + ", ".join(sorted(KINDS)))
    out = {"type": kind}
    if kind in ("heart_rate", "spo2", "steps") and ev.get("at") is not None:
        out["at"] = _num(ev["at"], 0, 4102444800, "at")
    if kind == "heart_rate":
        out["bpm"] = _num(ev.get("bpm"), 20, 250, "bpm")
    elif kind == "spo2":
        out["percent"] = _num(ev.get("percent"), 50, 100, "percent")
    elif kind == "steps":
        out["count"] = _num(ev.get("count"), 0, 100000, "count")
    elif kind == "notification":
        out.update(app=_text(ev.get("app"), 40, "app", True), title=_text(ev.get("title"), 80, "title"),
                   text=_text(ev.get("text"), 200, "text"))
    elif kind == "call":
        out.update(who=_text(ev.get("who"), 60, "who") or "an unknown number", kind=ev.get("kind", "incoming"))
        if out["kind"] not in ("incoming", "missed", "outgoing"):
            raise ValueError("kind must be incoming, missed or outgoing")
    elif kind == "app_usage":
        out.update(app=_text(ev.get("app"), 40, "app", True), state=ev.get("state", "opened"))
        if out["state"] not in ("opened", "closed"):
            raise ValueError("state must be opened or closed")
    return out


def _when(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError, OSError):
        return None


def is_batch(body):
    """The Health Connect Webhook app's payload: no "type", but a timestamp / app_version or lists of readings."""
    return isinstance(body, dict) and "type" not in body and any(
        k in body for k in ("app_version", "heart_rate", "oxygen_saturation", "steps"))


def expand(body, now):
    """Understands the "Health Connect Webhook" app's batches: {"heart_rate": [{"bpm", "time"}], "oxygen_saturation":
    [{"percentage", "time"}], "steps": [{"count", "time"}]} → separate clean events, each with its real time.
    Anything else is returned unchanged. Old or future-dated readings are dropped; data types she doesn't use are ignored."""
    if not is_batch(body):
        return [body]
    out = []
    for key, kind, field, name in (("heart_rate", "heart_rate", "bpm", "bpm"), ("oxygen_saturation", "spo2", "percentage", "percent"),
                                   ("steps", "steps", "count", "count")):
        rows = []
        for r in (body.get(key) or [])[:500]:
            if not isinstance(r, dict):
                continue
            t = _when(r.get("time"))
            if t is None or now - t > MAX_AGE or t - now > 120:
                continue
            rows.append((t, r.get(field)))
        for t, v in sorted(rows)[-200:]:
            out.append({"type": kind, name: v, "at": t})
    return out


class LinkServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, token, on_event, host="0.0.0.0", port=8766, allow_loopback=False, clock=time.time):
        if not token or len(token) < 16:
            raise ValueError("the link needs a secret token of at least 16 characters")
        super().__init__((host, port), Handler)
        self.token, self.on_event, self.allow_loopback, self.clock = token, on_event, allow_loopback, clock
        self.fails, self.hits, self.lock = {}, {}, threading.Lock()
        self.port = self.server_address[1]

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def stop(self):
        self.shutdown()
        self.server_close()

    # --- who may talk to me
    def source_ok(self, ip):
        return is_private(ip) or (self.allow_loopback and ip in ("127.0.0.1", "::1"))

    def blocked(self, ip):
        with self.lock:
            f = [t for t in self.fails.get(ip, []) if self.clock() - t < 600]
            self.fails[ip] = f
            return len(f) >= 10

    def fail(self, ip):
        with self.lock:
            self.fails.setdefault(ip, []).append(self.clock())

    def rate_ok(self, ip):
        with self.lock:
            now = self.clock()
            h = [t for t in self.hits.get(ip, []) if now - t < 60]
            h.append(now)
            self.hits[ip] = h
            return len(h) <= 120


class Handler(BaseHTTPRequestHandler):
    server_version = "ClaireLink"
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):                  # never log requests: the token may be in the address
        pass

    def _reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self):
        u = urlparse(self.path)
        given = self.headers.get("X-Claire-Link", "")
        parts = [p for p in u.path.split("/") if p]
        if not given and len(parts) == 2 and parts[0] == "e":
            given = parts[1]
        if not given:
            given = (parse_qs(u.query).get("k") or [""])[0]
        return hmac.compare_digest(given.encode(), self.server.token.encode())

    def _gate(self):
        s, ip = self.server, self.client_address[0]
        if not s.source_ok(ip):
            self._reply(403, {"error": "this device is not on your private network"})
            return False
        if s.blocked(ip):
            self._reply(429, {"error": "too many wrong tries; wait ten minutes"})
            return False
        if not self._token_ok():
            s.fail(ip)
            self._reply(403, {"error": "wrong or missing token"})
            return False
        if not s.rate_ok(ip):
            self._reply(429, {"error": "slow down"})
            return False
        return True

    def do_GET(self):                           # lets you test from the phone's browser
        if self._gate():
            self._reply(200, {"ok": True, "message": "C.L.A.I.R.E. link is working"})

    def do_POST(self):
        if not self._gate():
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._reply(400, {"error": "bad length"})
        if n <= 0 or n > MAX_BODY:
            return self._reply(413 if n > MAX_BODY else 400, {"error": f"send 1 to {MAX_BODY} bytes of JSON"})
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            events = []
            for e in expand(body, self.server.clock()):
                try:
                    events.append(validate(e))
                except ValueError:
                    if not is_batch(body):                  # one bad reading in a big batch must not fail the whole sync
                        raise
        except (ValueError, UnicodeDecodeError) as e:
            return self._reply(400, {"error": str(e)})
        try:
            for ev in events:
                self.server.on_event(ev)
        except Exception:
            return self._reply(500, {"error": "I couldn't process that"})
        self._reply(200, {"ok": True})
