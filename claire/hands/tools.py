"""Her hands. Reading is free; anything that opens or changes something waits for Carl's "yes".
There is deliberately no tool to delete, send, install or run commands."""
import itertools
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import files, sysinfo
from .files import Refused
from .platform import Platform

EXPIRES = 300                                   # an unanswered question is dropped after 5 minutes
YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|please do|go on|confirm|approved?)\b[\s,.!]*"
                 r"(please|claire)?[\s.!]*$", re.I)
ALWAYS = re.compile(r"^\s*(yes|yeah|ok|okay)?[\s,]*(always|every time|don'?t ask (me )?again)\b", re.I)
NO = re.compile(r"^\s*(no|nope|nah|cancel|don'?t|do not|stop|never ?mind|forget it|deny|denied)\b", re.I)

SPECS = [
    {"name": "system_status", "ask": False,
     "description": "Check how this PC is doing: processor load, memory, disk space, battery, uptime.",
     "properties": {"topic": {"type": "string", "enum": list(sysinfo.TOPICS)}}, "required": []},
    {"name": "find_files", "ask": False,
     "description": "Search file and folder names in the user's Documents, Downloads and Desktop. Does not open anything.",
     "properties": {"query": {"type": "string", "description": "words from the file name"}}, "required": ["query"]},
    {"name": "open_file", "ask": True,
     "description": "Open a file or folder (full path, found with find_files) in its normal program. Asks the user first.",
     "properties": {"path": {"type": "string"}}, "required": ["path"]},
    {"name": "open_app", "ask": True,
     "description": "Start one of the user's apps (notepad, calculator, paint, file explorer, settings, edge, chrome, "
                    "task manager). Asks the user first.",
     "properties": {"name": {"type": "string"}}, "required": ["name"]},
    {"name": "open_website", "ask": True,
     "description": "Open a web address (http or https) in the browser. Asks the user first.",
     "properties": {"url": {"type": "string"}}, "required": ["url"]},
    {"name": "set_volume", "ask": True,
     "description": "Turn the PC volume up or down a step, or mute/unmute. Asks the user first.",
     "properties": {"action": {"type": "string", "enum": ["up", "down", "mute"]}}, "required": ["action"]},
]
BY_NAME = {s["name"]: s for s in SPECS}


def check_url(text):
    s = str(text or "").strip()
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", s, re.I) and "." in s and " " not in s and ":" not in s.split("/")[0]:
        s = "https://" + s                                    # "example.com" -> https://example.com
    if len(s) > 2000 or re.search(r"[\x00-\x20\x7f]", s):
        raise Refused("That doesn't look like a safe web address.")
    u = urlparse(s)
    if u.scheme.lower() not in ("http", "https"):
        raise Refused("I only open http and https web addresses.")
    if not u.hostname or "." not in u.hostname and u.hostname != "localhost":
        raise Refused("That doesn't look like a web address.")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise Refused("I won't open addresses with a hidden login or '@' in them — they are often tricks.")
    return s


class Pending:
    def __init__(self, pid, name, args, what, at):
        self.id, self.name, self.args, self.what, self.at = pid, name, args, what, at

    def view(self):
        return {"id": self.id, "tool": self.name, "what": self.what}


class Hands:
    def __init__(self, cfg, platform=None, log_path=None, clock=time.time):
        self.cfg, self.t = cfg, cfg.get("tools", {})
        self.platform = platform or Platform()
        self.clock = clock
        self.log_path = Path(log_path or Path(cfg["data_dir"]) / "actions.jsonl")
        self._ids = itertools.count(1)
        self._pending, self._lock = {}, threading.RLock()
        self.always = set(self.t.get("always", [])) & {n for n, s in BY_NAME.items() if s["ask"]}
        self.persist = None                                    # called with (key, value) to save a setting
        self.on_done = None                                    # called after an action really happened
        self.on_change = None                                  # called when the pending list changes

    # ---- what the brain is told ------------------------------------------------------------
    @property
    def enabled(self):
        return bool(self.t.get("enabled", True))

    def specs(self):
        return [{"type": "function", "function": {
            "name": s["name"], "description": s["description"],
            "parameters": {"type": "object", "properties": s["properties"], "required": s["required"]}}}
            for s in SPECS] if self.enabled else []

    def allowed(self):
        return files.roots(self.t.get("folders"))

    # ---- audit -----------------------------------------------------------------------------
    def log(self, event, name, args, text=""):
        row = {"at": datetime.now().isoformat(timespec="seconds"), "event": event, "tool": name,
               "args": args, "text": text[:300]}
        try:
            with self._lock, open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def history(self, limit=40):
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    # ---- calling a tool --------------------------------------------------------------------
    def call(self, name, args):
        """Returns {"status": "done"|"pending"|"error", "text": ..., "id": ...}."""
        args = args if isinstance(args, dict) else {}
        spec = BY_NAME.get(name)
        if not self.enabled:
            return {"status": "error", "text": "My hands are switched off in settings."}
        if not spec:
            return {"status": "error", "text": f"I don't have a tool called {name}."}
        try:
            what = self._prepare(name, args)                  # validates; raises Refused
        except Refused as e:
            self.log("refused", name, args, str(e))
            return {"status": "error", "text": str(e)}
        if not spec["ask"]:
            return self._run(name, args, what)
        if name in self.always:
            return self._run(name, args, what)
        with self._lock:
            self._expire()
            for p in self._pending.values():                  # asking the same thing twice is one question
                if p.name == name and p.args == args:
                    return {"status": "pending", "id": p.id, "text": f"Waiting for your yes: {p.what}"}
            pid = next(self._ids)
            self._pending[pid] = Pending(pid, name, dict(args), what, self.clock())
        self.log("asked", name, args, what)
        self._changed()
        return {"status": "pending", "id": pid, "text": f"{what}? I'm waiting for your yes."}

    def _prepare(self, name, args):
        """Check the request and describe it in plain words. Never touches the PC."""
        if name == "system_status":
            return "Check how the PC is doing"
        if name == "find_files":
            if not self.allowed():
                raise Refused("None of my allowed folders exist. Set them in settings.json under tools.folders.")
            return f"Search for {str(args.get('query', '')).strip()[:60]}"
        if name == "open_file":
            real = files.check_openable(files.check_path(args.get("path"), self.allowed()))
            args["path"] = str(real)
            return f"Open {'the folder' if real.is_dir() else 'the file'} {real}"
        if name == "open_app":
            key = str(args.get("name", "")).strip().lower()
            apps = {k.lower(): v for k, v in self.t.get("apps", {}).items()}
            if key not in apps:
                known = ", ".join(sorted(apps)) or "none"
                raise Refused(f"I only open apps on my list. I can open: {known}.")
            args["name"] = key
            return f"Open {key.title() if key.islower() else key}"
        if name == "open_website":
            url = check_url(args.get("url"))
            args["url"] = url
            return f"Open the website {url}"
        if name == "set_volume":
            act = str(args.get("action", "")).lower()
            if act not in ("up", "down", "mute"):
                raise Refused("I can turn the volume up, down, or mute it.")
            if not self.platform.can_change_volume():
                raise Refused("I can only change the volume on Windows.")
            args["action"] = act
            return {"up": "Turn the volume up", "down": "Turn the volume down", "mute": "Mute or unmute the sound"}[act]
        raise Refused("Unknown tool.")

    def _run(self, name, args, what):
        try:
            text = getattr(self, "_do_" + name)(args)
        except Refused as e:
            self.log("refused", name, args, str(e))
            return {"status": "error", "text": str(e)}
        except Exception as e:                                # the PC said no; report, never crash her
            self.log("failed", name, args, repr(e))
            return {"status": "error", "text": f"That didn't work ({type(e).__name__})."}
        self.log("done", name, args, text)
        if BY_NAME[name]["ask"] and self.on_done:
            try:
                self.on_done()
            except Exception:
                pass
        return {"status": "done", "text": text}

    def _do_system_status(self, a):
        return sysinfo.describe(sysinfo.read(), str(a.get("topic", "all")).lower())

    def _do_find_files(self, a):
        found = files.find(a.get("query"), self.allowed())
        if not found:
            return "I didn't find anything with that name in Documents, Downloads or Desktop."
        return "I found:\n" + "\n".join(found)

    def _do_open_file(self, a):
        self.platform.open_path(a["path"])
        return f"Opened {a['path']}."

    def _do_open_app(self, a):
        apps = {k.lower(): v for k, v in self.t.get("apps", {}).items()}
        self.platform.launch(apps[a["name"]])
        return f"Opened {a['name']}."

    def _do_open_website(self, a):
        self.platform.open_path(a["url"])
        return f"Opened {a['url']}."

    def _do_set_volume(self, a):
        step = max(2, min(30, int(self.t.get("volume_step", 10))))
        if a["action"] == "mute":
            self.platform.volume_taps("mute", 1)
            return "Toggled mute."
        self.platform.volume_taps(a["action"], step // 2)
        return f"Volume {a['action']} a little."

    # ---- Carl's answer ---------------------------------------------------------------------
    def pending(self):
        with self._lock:
            self._expire()
            return [p.view() for p in self._pending.values()]

    def _expire(self):
        now = self.clock()
        for pid in [i for i, p in self._pending.items() if now - p.at > EXPIRES]:
            p = self._pending.pop(pid)
            self.log("expired", p.name, p.args, p.what)

    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def approve(self, pid, always=False):
        with self._lock:
            self._expire()
            p = self._pending.pop(int(pid), None)
        if not p:
            return {"status": "error", "text": "That question has already been answered or timed out."}
        if always and BY_NAME[p.name]["ask"]:
            self.always.add(p.name)
            self.t["always"] = sorted(self.always)
            if self.persist:
                self.persist("tools.always", sorted(self.always))
        self.log("approved", p.name, p.args, "always" if always else "")
        self._changed()
        res = self._run(p.name, dict(p.args), p.what)
        res["always"] = bool(always) and res["status"] == "done"
        return res

    def deny(self, pid):
        with self._lock:
            p = self._pending.pop(int(pid), None)
        if not p:
            return {"status": "error", "text": "That question has already been answered or timed out."}
        self.log("denied", p.name, p.args, p.what)
        self._changed()
        return {"status": "denied", "text": f"Okay, I won't. ({p.what})"}

    def answer(self, text):
        """Carl said (or typed) something while a question is open. Returns a sentence to say, or None if he
        was talking about something else. With several questions open, the newest one is answered."""
        pend = self.pending()
        if not pend:
            return None
        pid = pend[-1]["id"]
        if ALWAYS.match(text):
            return self.approve(pid, always=True)["text"] + " I won't ask about that again."
        if YES.match(text):
            return self.approve(pid)["text"]
        if NO.match(text):
            return self.deny(pid)["text"]
        return None
