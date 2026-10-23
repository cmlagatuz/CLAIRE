"""Her companion side: events from your phone and watch, health alerts, reminders, notes and break reminders — all
in one place so the window and the terminal behave the same."""
import json
import re
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
    "emergency_number": "997",               # what her dialer offer opens (digits only); 997 = ambulance in Saudi Arabia
    "loud_alerts": True,                     # urgent health alerts turn this PC's volume up first
}
YES = re.compile(r"^\W*(yes|yeah|yep|yup|please|do it|go ahead|call|open( it| the dialer)?|ok(ay)?)\b", re.I)
NO = re.compile(r"^\W*(no|nope|nah|cancel|stop|don'?t|i'?m (fine|ok|okay))\b", re.I)


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
        self.phone_open, self.offer, self.loud_at = None, None, -1e9
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
        if urgent:
            self._louder()
            self.offer = self.clock()
        self._say(text, urgent)
        if urgent or "break" in text.lower():
            self.notify_phone()
        return True

    def alert(self, text, urgent=False):
        self.speak(text, urgent=urgent)

    def _louder(self):
        """Urgent health alerts must be heard: turn the PC's volume up (at most once every five minutes)."""
        if not self.c.get("loud_alerts", True) or self.clock() - self.loud_at < 300:
            return
        self.loud_at = self.clock()
        try:
            if self.platform.can_change_volume():
                self.platform.volume_taps("up", 25)                 # about +50%
        except Exception:
            pass

    def dial(self):
        """Open the phone's dialer with the emergency number typed in (never places the call: you press call).
        Needs the phone connected over adb; otherwise she says so plainly."""
        num = str(self.c.get("emergency_number") or "997")
        if not re.fullmatch(r"\+?\d{2,15}", num):
            num = "997"
        try:
            code, out = self.platform.adb(["shell", "am", "start", "-a", "android.intent.action.DIAL", "-d", f"tel:{num}"],
                                          self.tools.get("adb_path") or "adb")
            ok = code == 0 and "error" not in out.lower()
        except Exception:
            ok = False
        if ok:
            return f"I've opened the dialer on your phone with {num} ready. Press the green call button now."
        return f"I couldn't reach your phone from here. Please dial {num} yourself right now."

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

    def _store_health(self, kind, value, at=None):
        try:
            with open(self.health_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": self.clock() if at is None else at, "k": kind, "v": value}) + "\n")
        except OSError:
            pass

    # ---------------------------------------------------------------- events from the phone / watch
    def handle_event(self, ev):
        k = ev["type"]
        if k in ("heart_rate", "spo2", "steps"):
            kind, val = {"heart_rate": ("hr", ev.get("bpm")), "spo2": ("spo2", ev.get("percent")),
                         "steps": ("steps", ev.get("count"))}[k]
            self.vitals.add(kind, val, ev.get("at"))
            self._store_health(kind, val, ev.get("at"))
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
            self._louder()
            self.notify_phone()
            self.offer = self.clock()
            return health.EMERGENCY_REPLY
        if self.offer is not None and self.clock() - self.offer < 900:
            if YES.match(text):
                self.offer = None
                return self.dial()
            if NO.match(text):
                self.offer = None
                return "Okay. If it gets worse, or you're unsure, call the emergency number straight away."
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
                self.server = link.LinkServer(lk["token"], self.handle_event, port=int(lk.get("port", 8766)),
                                              allow_loopback=True)                        # this PC itself may test it
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


def start_test_server(token, port, out=print):
    """The link, running on its own so you can test it before (or without) opening her window. Prints what arrives."""
    def show(ev):
        out("   received: " + ", ".join(f"{k}={v}" for k, v in ev.items()))
    srv = link.LinkServer(token, show, port=int(port), allow_loopback=True)
    srv.start()
    return srv


def setup_link():
    """link.bat : switch the phone link on, make a secret token, print the address(es), and listen so you can test it."""
    from . import config
    from .hands.platform import Platform
    cfg = config.load()
    lk = settings(cfg)["link"]
    token = lk["token"] if len(lk.get("token", "")) >= 16 else new_token()
    config.save_setting("companion.link.enabled", True)
    config.save_setting("companion.link.token", token)
    port = int(lk.get("port", 8766))
    ips = Platform().addresses() or ["<this PC's address>"]
    print(f"""
=== C.L.A.I.R.E. phone link ===
The link is switched ON. Keep the address below secret, like a password.

  Addresses to try on your phone (same Wi-Fi). A PC can have several; the first is the most likely:""")
    for ip in ips:
        print(f"      http://{ip}:{port}/e/{token}")
    print(f"""
  1. Open one of them in the PHONE's browser. It should say "link is working".
  2. If it says "took too long to respond":
       - the phone must be on the same Wi-Fi as this PC (not mobile data, not a guest network, no VPN);
       - Windows Firewall must allow it. Open PowerShell AS ADMINISTRATOR once and run:
           netsh advfirewall firewall add rule name="CLAIRE link" dir=in action=allow protocol=TCP localport={port} profile=private
       - the Wi-Fi must be set to a PRIVATE network (Settings > Network > Wi-Fi > your network > Private);
       - try the next address in the list above.
  3. To test from this PC first, open the same address with 127.0.0.1 instead of the number.

  Events to send (POST, JSON), for example:
      {{"type": "heart_rate", "bpm": 72}}   {{"type": "spo2", "percent": 97}}
      {{"type": "notification", "app": "WhatsApp", "title": "Ali"}}
      {{"type": "call", "who": "Mum", "kind": "missed"}}
      {{"type": "app_usage", "app": "Instagram", "state": "opened"}}   (and "closed")

  If the address ever leaks: delete "token" under companion > link in settings.json, then run link.bat again.
""")
    try:
        srv = start_test_server(token, port)
    except OSError:
        print(f"  (Port {port} is already in use — the link is probably already running inside her window. That is fine:\n"
              "   test the address above from the phone.)")
        return
    print(f"  TEST MODE: listening on port {port} now. Open the address on your phone; anything it sends appears below.")
    print("  Press Ctrl+C to stop. (When her window is open it runs the link itself, so close this first.)\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
        print("  Stopped.")
