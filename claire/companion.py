"""Her companion side: events from your phone and watch, health alerts, reminders, notes and break reminders — all
in one place so the window and the terminal behave the same."""
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from . import health, link, reminders, wellbeing

DEFAULTS = {
    "enabled": True,
    "link": {"enabled": False, "port": 8766, "token": "", "read_message_text": False},
    "breaks": {"enabled": True, "same_app_minutes": 90, "continuous_minutes": 120},
    "quiet_hours": ["23:00", "07:00"],       # she stays silent (except for urgent health alerts)
    "notify_shortcut": "",                   # a name from tools.shortcuts: how she reaches your phone/watch for alerts
}


def settings(cfg):
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (cfg.get("companion") or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def in_quiet(now, quiet):
    try:
        a, b = (datetime.strptime(x, "%H:%M").time() for x in quiet)
    except (ValueError, TypeError):
        return False
    t = now.time()
    return (a <= t or t < b) if a > b else (a <= t < b)


class Companion:
    def __init__(self, cfg, platform, say, tools=None, clock=time.time, now=datetime.now):
        self.cfg, self.c = cfg, settings(cfg)
        self.platform, self._say, self.clock, self.now = platform, say, clock, now
        self.tools = tools if tools is not None else (cfg.get("tools") or {})
        d = cfg["data_dir"]
        self.vitals = health.Vitals(clock)
        self.monitor = health.Monitor(self.vitals, self.alert, clock)
        self.reminders = reminders.Reminders(d, now)
        b = self.c["breaks"]
        self.usage = wellbeing.Usage(b["same_app_minutes"], b["continuous_minutes"], clock=clock)
        self.phone_usage = wellbeing.Usage(b["same_app_minutes"], b["continuous_minutes"], clock=clock)
        self.phone_open = None
        self.health_log = Path(d) / "health.jsonl"
        self.missed, self.burst, self.last_spoken = [], [], 0.0
        self.server, self.stop_ev = None, threading.Event()
        self._load_health()

    # ---------------------------------------------------------------- speaking
    def speak(self, text, urgent=False):
        quiet = in_quiet(self.now(), self.c["quiet_hours"])
        if quiet and not urgent:
            self.missed.append(text)
            return False
        self._say(text, urgent)
        if urgent or "break" in text.lower():
            self.notify_phone()
        return True

    def alert(self, text, urgent=False):
        self.speak(text, urgent=urgent)

    def notify_phone(self):
        name = str(self.c.get("notify_shortcut") or "").lower()
        sc = {k.lower(): v for k, v in (self.tools.get("shortcuts") or {}).items()}
        if name and name in sc:
            try:
                self.platform.http_get(sc[name])
            except Exception:
                pass

    # ---------------------------------------------------------------- health data stays on this PC
    def _load_health(self):
        try:
            for line in self.health_log.read_text(encoding="utf-8").splitlines()[-6000:]:
                r = json.loads(line)
                if self.clock() - r["t"] <= self.vitals.keep and r["k"] in self.vitals.d:
                    self.vitals.d[r["k"]].append((r["t"], r["v"]))
        except (OSError, ValueError, KeyError):
            pass

    def _store_health(self, kind, value):
        try:
            with open(self.health_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": self.clock(), "k": kind, "v": value}) + "\n")
        except OSError:
            pass

    # ---------------------------------------------------------------- events from the phone / watch
    def handle_event(self, ev):
        k = ev["type"]
        if k in ("heart_rate", "spo2", "steps"):
            kind, val = {"heart_rate": ("hr", ev.get("bpm")), "spo2": ("spo2", ev.get("percent")),
                         "steps": ("steps", ev.get("count"))}[k]
            self.vitals.add(kind, val)
            self._store_health(kind, val)
            self.monitor.check()
        elif k == "notification":
            who = ev["title"] or "Someone"
            text = f"{who} — {ev['app']}"
            if self.c["link"].get("read_message_text") and ev.get("text"):
                text += f": {ev['text']}"
            self.burst.append(text)
        elif k == "call":
            who, kind = ev["who"], ev["kind"]
            self.burst.append({"missed": f"Missed call from {who}", "incoming": f"{who} is calling you",
                               "outgoing": f"Call to {who}"}[kind])
        elif k == "app_usage":
            if ev["state"] == "opened":
                self.phone_open = (ev["app"], self.clock())
            elif self.phone_open and self.phone_open[0] == ev["app"]:
                self.phone_open = None
        self.flush()

    def flush(self):
        """Say new phone notifications (batched, never a flood)."""
        if not self.burst or self.clock() - self.last_spoken < 8:
            return
        items, self.burst = self.burst, []
        text = items[0] if len(items) == 1 else f"{len(items)} new things on your phone: " + "; ".join(items[:3]) + \
            (f" and {len(items) - 3} more" if len(items) > 3 else "")
        if self.speak(text):
            self.last_spoken = self.clock()

    # ---------------------------------------------------------------- what Carl says
    def answer(self, text):
        """Emergency words, or a reply to a health check-in. Returns what to say, or None."""
        if health.EMERGENCY.search(text):
            self.notify_phone()
            return health.EMERGENCY_REPLY
        return self.monitor.reply(text)

    # ---------------------------------------------------------------- the heartbeat
    def tick(self):
        for r in self.reminders.due():
            self.speak(f"Reminder: {r['text']}.", urgent=False)
        if self.c["breaks"]["enabled"]:
            app = None
            try:
                app = self.platform.foreground_app()
                idle = self.platform.idle_seconds()
            except Exception:
                idle = 0
            msg = self.usage.sample(app, idle) if app else self.usage.sample(None)
            if msg:
                self.speak(msg)
            if self.phone_open:
                if self.clock() - self.phone_open[1] > 4 * 3600:
                    self.phone_open = None                       # no "closed" event for hours: assume it ended
                else:
                    pm = self.phone_usage.sample("phone:" + self.phone_open[0])
                    if pm:
                        self.speak(pm.replace("phone:", "your phone's "))
            else:
                self.phone_usage.sample(None)
        self.monitor.check()
        self.flush()
        if self.missed and not in_quiet(self.now(), self.c["quiet_hours"]):
            n, self.missed = len(self.missed), []
            self._say(f"While it was quiet I held back {n} thing{'s' if n != 1 else ''}. Ask me \"what did I miss\" any time.", False)

    # ---------------------------------------------------------------- life cycle
    def start(self):
        lk = self.c["link"]
        if lk.get("enabled") and not self.server:
            try:
                self.server = link.LinkServer(lk["token"], self.handle_event, port=int(lk.get("port", 8766)))
                self.server.start()
            except (OSError, ValueError) as e:
                self._say(f"My phone link couldn't start: {e}", False)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.stop_ev.wait(30):
            try:
                self.tick()
            except Exception:
                pass

    def stop(self):
        self.stop_ev.set()
        if self.server:
            self.server.stop()

    # ---------------------------------------------------------------- one line for her system prompt
    def brief(self):
        t = self.reminders.today()
        return ("Reminders due today: " + "; ".join(r["text"] for r in t)) if t else ""


def new_token():
    return secrets.token_urlsafe(24)


def build(claire, say, platform=None):
    """A Companion for this Claire, hooked to her hands (tools). `say(text, urgent=False)` shows/speaks things."""
    from .hands.platform import Platform
    if not settings(claire.cfg)["enabled"]:
        return None
    comp = Companion(claire.cfg, platform or Platform(), say)
    if claire.hands:
        claire.hands.companion = comp
    return comp


def setup_link():
    """python -m claire --link : switch the phone link on, make a secret token, and print how to use it."""
    from . import config
    from .hands.platform import Platform
    cfg = config.load()
    lk = settings(cfg)["link"]
    token = lk["token"] if len(lk.get("token", "")) >= 16 else new_token()
    config.save_setting("companion.link.enabled", True)
    config.save_setting("companion.link.token", token)
    try:
        ip = Platform().local_ip()
    except OSError:
        ip = "<this PC's address>"
    port = lk.get("port", 8766)
    base = f"http://{ip}:{port}/e/{token}"
    print(f"""
=== C.L.A.I.R.E. phone link ===
The link is switched ON (restart her window to start it). Windows may ask to allow Python through the firewall:
choose PRIVATE networks only.

  Address for your phone/watch automations (keep it secret, like a password):
      {base}

  Test in your phone's browser (same Wi-Fi):   open that address — it should say "link is working".
  Send an event (POST, JSON body) to the same address, for example:
      {{"type": "heart_rate", "bpm": 72}}
      {{"type": "spo2", "percent": 97}}
      {{"type": "notification", "app": "WhatsApp", "title": "Ali"}}
      {{"type": "call", "who": "Mum", "kind": "missed"}}
      {{"type": "app_usage", "app": "Instagram", "state": "opened"}}   (and "closed")

  Only devices on your private network can use it. If the address ever leaks, run this command again after
  deleting "token" from settings.json to get a new one.
""")
