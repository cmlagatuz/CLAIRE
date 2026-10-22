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

from .. import config as _config
from . import files, net, phone, procs, selfedit, sysinfo
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
    {"name": "top_processes", "ask": False,
     "description": "Look at what is running (like Task Manager): the programs using the most memory.",
     "properties": {"count": {"type": "integer", "description": "how many programs, default 5"}}, "required": []},
    {"name": "close_program", "ask": True,
     "description": "Politely ask a running program to close to free memory (never forced; never Windows parts). "
                    "Use the name from top_processes. Asks the user first.",
     "properties": {"name": {"type": "string"}}, "required": ["name"]},
    {"name": "read_own_file", "ask": False,
     "description": "Read one of my own code files (e.g. claire/core.py) so I can improve it.",
     "properties": {"path": {"type": "string"}}, "required": ["path"]},
    {"name": "propose_change", "ask": False,
     "description": "Prepare an edit to my own code: replace the exact text 'old' (appears once) with 'new' in 'path'; "
                    "leave 'old' empty to create a new file. I test it on a copy; nothing real changes yet.",
     "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
                    "reason": {"type": "string"}}, "required": ["path", "new", "reason"]},
    {"name": "show_change", "ask": False,
     "description": "Show a prepared change (its diff and test result) by number.",
     "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    {"name": "apply_change", "ask": True,
     "description": "Apply a prepared change whose tests passed. Asks the user first.",
     "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    {"name": "undo_change", "ask": True,
     "description": "Undo one of my applied changes (the latest if no id). Asks the user first.",
     "properties": {"id": {"type": "integer"}}, "required": []},
    {"name": "network_map", "ask": False,
     "description": "Look at the devices on the user's own Wi-Fi/home network (read-only) and flag ones not seen before.",
     "properties": {}, "required": []},
    {"name": "network_trust", "ask": True,
     "description": "Remember the devices just listed by network_map as the user's own, so new ones can be flagged. Asks first.",
     "properties": {}, "required": []},
    {"name": "phone_status", "ask": False,
     "description": "Check the user's Android/Samsung phone over Wi-Fi: model and battery (read-only).",
     "properties": {}, "required": []},
    {"name": "phone_connect", "ask": True,
     "description": "Connect to the user's phone by its Wi-Fi address like 192.168.1.20:5555 (Wireless debugging). Asks first.",
     "properties": {"address": {"type": "string"}}, "required": ["address"]},
    {"name": "phone_open_app", "ask": True,
     "description": "Open an app on the user's phone from the user's list (e.g. whatsapp, camera). Asks first.",
     "properties": {"name": {"type": "string"}}, "required": ["name"]},
    {"name": "run_shortcut", "ask": True,
     "description": "Run one of the user's named shortcuts (e.g. buzz my watch, lights on) from their list. Asks first.",
     "properties": {"name": {"type": "string"}}, "required": ["name"]},
    {"name": "search_documents", "ask": False,
     "description": "Search the user's own documents (notes, reports, PDFs…) and return passages WITH their sources. "
                    "Use it for questions about what is in his files; answer only from the passages and cite them like [1].",
     "properties": {"query": {"type": "string"}}, "required": ["query"]},
    {"name": "index_documents", "ask": False,
     "description": "Refresh my index of the user's documents (new and changed files only).",
     "properties": {}, "required": []},
    {"name": "health_status", "ask": False,
     "description": "The latest readings from the user's watch (heart rate, blood oxygen) and how old they are.",
     "properties": {}, "required": []},
    {"name": "add_reminder", "ask": False,
     "description": "Remind the user at a date/time (birthdays, appointments). 'when' is YYYY-MM-DD or YYYY-MM-DDTHH:MM "
                    "(work it out from today's date); 'repeat' is none, daily, weekly, monthly or yearly (yearly for birthdays).",
     "properties": {"text": {"type": "string"}, "when": {"type": "string"},
                    "repeat": {"type": "string", "enum": ["none", "daily", "weekly", "monthly", "yearly"]}},
     "required": ["text", "when"]},
    {"name": "list_reminders", "ask": False,
     "description": "Show the user's upcoming reminders.", "properties": {}, "required": []},
    {"name": "remove_reminder", "ask": True,
     "description": "Delete one reminder by its number. Asks first.",
     "properties": {"id": {"type": "integer"}}, "required": ["id"]},
    {"name": "take_note", "ask": False,
     "description": "Write down a note for the user.",
     "properties": {"text": {"type": "string"}}, "required": ["text"]},
    {"name": "list_notes", "ask": False,
     "description": "Show the user's latest notes, or search them.",
     "properties": {"query": {"type": "string"}}, "required": []},
    {"name": "screen_time", "ask": False,
     "description": "How long the user has used apps today (this PC and phone).", "properties": {}, "required": []},
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
GROUPS = {   # which tools are shown to the model for which kind of request (19+ tools at once make a 7B model slow and muddled)
    "pc": ("system_status", "find_files", "open_file", "open_app", "open_website", "set_volume", "top_processes",
           "close_program"),
    "self": ("read_own_file", "propose_change", "show_change", "apply_change", "undo_change"),
    "devices": ("network_map", "network_trust", "phone_status", "phone_connect", "phone_open_app", "run_shortcut"),
    "docs": ("search_documents", "index_documents"),
    "life": ("health_status", "add_reminder", "list_reminders", "remove_reminder", "take_note", "list_notes", "screen_time"),
}
NO_ALWAYS = {"apply_change", "undo_change", "close_program"}     # these are asked every single time, whatever you say


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
    def __init__(self, pid, name, args, what, at, detail=""):
        self.id, self.name, self.args, self.what, self.at, self.detail = pid, name, args, what, at, detail

    def view(self):
        return {"id": self.id, "tool": self.name, "what": self.what, "detail": self.detail}


class Hands:
    def __init__(self, cfg, platform=None, log_path=None, clock=time.time, root=None, runner=None):
        self.cfg, self.t = cfg, cfg.get("tools", {})
        self.platform = platform or Platform()
        self.clock = clock
        self.log_path = Path(log_path or Path(cfg["data_dir"]) / "actions.jsonl")
        self._ids = itertools.count(1)
        self._pending, self._lock = {}, threading.RLock()
        self.always = set(self.t.get("always", [])) & {n for n, s in BY_NAME.items() if s["ask"]} - NO_ALWAYS
        self.selfedit = selfedit.SelfEdit(root or _config.ROOT, cfg["data_dir"], runner or selfedit.run_tests)
        from ..knowledge import Knowledge
        self.knowledge = Knowledge(cfg)
        self.companion = None                                  # set by the window / terminal (Phase 4.8)
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

    def specs_for(self, text="", all_tools=False):
        """Only the tool groups this message is about (all of them for a follow-up like "yes, that one")."""
        from ..core import GROUP_WORDS
        names = set()
        for g, rx in GROUP_WORDS.items():
            if all_tools or rx.search(text or ""):
                names.update(GROUPS[g])
        return [sp for sp in self.specs() if sp["function"]["name"] in names] or self.specs()

    def auto_close(self):
        """Programs Carl listed in settings.json (tools.auto_close) that she may close without asking. Only he can add to it."""
        return {procs.key(n) for n in self.t.get("auto_close", []) if isinstance(n, str) and not procs.protected(n)}

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
        if name in self.always or (name == "close_program" and procs.key(args.get("name")) in self.auto_close()):
            return self._run(name, args, what)
        with self._lock:
            self._expire()
            for p in self._pending.values():                  # asking the same thing twice is one question
                if p.name == name and p.args == args:
                    return {"status": "pending", "id": p.id, "text": f"Waiting for your yes: {p.what}"}
            pid = next(self._ids)
            detail = ""
            if name == "apply_change":                          # you see exactly what she wants to change
                try:
                    detail = self.selfedit.load(args["id"])["diff"][:2500]
                except Refused:
                    pass
            self._pending[pid] = Pending(pid, name, dict(args), what, self.clock(), detail)
        self.log("asked", name, args, what)
        self._changed()
        return {"status": "pending", "id": pid, "text": f"{what}? I'm waiting for your yes."}

    def _prepare(self, name, args):
        """Check the request and describe it in plain words. Never touches the PC."""
        if name == "system_status":
            return "Check how the PC is doing"
        if name == "top_processes":
            return "Look at what is running"
        if name == "close_program":
            n = str(args.get("name", "")).strip()
            if not procs.NAME_OK.match(n):
                raise Refused("That isn't a program name I can use.")
            if procs.protected(n):
                raise Refused(f"{procs.key(n).title()} is part of Windows or part of me — I never close those.")
            g = procs.resolve(procs.group(self.platform.list_processes()), n)
            if not g:
                raise Refused(f"I don't see {n} running.")
            if procs.protected(g[0]["name"]):
                raise Refused(f"{procs.key(g[0]['name']).title()} is part of Windows or part of me — I never close those.")
            args["name"] = g[0]["name"]
            return (f"Close {procs.key(g[0]['name']).title()} ({g[0]['count']} process{'es' if g[0]['count'] != 1 else ''}, "
                    f"{procs.size(g[0]['mb'])}) — unsaved work in it could be lost")
        if name in ("read_own_file", "propose_change", "show_change"):
            if name == "show_change":
                self.selfedit.load(args.get("id"))
            else:
                self.selfedit.rel(args.get("path"), for_write=name == "propose_change")
            return {"read_own_file": "Read my own file", "propose_change": "Prepare a change to my code",
                    "show_change": "Show a prepared change"}[name]
        if name == "apply_change":
            prop, _ = self.selfedit.check_ready(args.get("id"))
            args["id"] = prop["id"]
            return (f"Change my own code: apply change #{prop['id']} to {prop['path']} (+{prop['plus']} −{prop['minus']} lines, "
                    f"all my tests pass) — {prop['reason'] or 'no reason given'}")
        if name == "undo_change":
            done = [p for p in self.selfedit.list() if p["status"] == "applied"]
            pid = args.get("id") or (done[-1]["id"] if done else None)
            prop = self.selfedit.load(pid) if pid else None
            if not prop or prop["status"] != "applied":
                raise Refused("There is nothing of mine to undo.")
            args["id"] = prop["id"]
            return f"Undo change #{prop['id']} to {prop['path']}"
        if name == "network_map":
            return "Look at the devices on my network"
        if name == "network_trust":
            if not getattr(self, "last_devices", None):
                raise Refused("Let me look at the network first — ask me to scan it.")
            return f"Remember these {len(self.last_devices)} devices as yours, so I can warn you about new ones"
        if name == "phone_status":
            return "Check the phone"
        if name == "phone_connect":
            args["address"] = phone.check_address(args.get("address"))
            return f"Connect to your phone at {args['address']}"
        if name == "phone_open_app":
            key, _pkg = phone.check_app(args.get("name"), self.t.get("phone_apps"))
            args["name"] = key
            return f"Open {key.title()} on your phone"
        if name == "run_shortcut":
            key = str(args.get("name", "")).strip().lower()
            sc = {k.lower(): v for k, v in (self.t.get("shortcuts") or {}).items()}
            if key not in sc:
                raise Refused("I only run shortcuts on my list. I have: " + (", ".join(sorted(sc)) or "none yet — add them in settings.json under tools.shortcuts") + ".")
            self._shortcut_url(sc[key])
            args["name"] = key
            return f"Run your shortcut “{key}”"
        if name == "search_documents":
            if not str(args.get("query", "")).strip():
                raise Refused("What should I look for in your documents?")
            return "Search your documents"
        if name == "index_documents":
            return "Refresh my index of your documents"
        if name in ("health_status", "list_reminders", "list_notes", "screen_time", "take_note", "add_reminder",
                    "remove_reminder"):
            if not self.companion:
                raise Refused("My companion features aren't running right now.")
            if name == "add_reminder":
                from .. import reminders as _r
                try:
                    _r.parse_when(args.get("when"), self.companion.now())
                except _r.Refused as e:
                    raise Refused(str(e))
                return "Set a reminder"
            if name == "remove_reminder":
                ids = {r["id"]: r for r in self.companion.reminders._load()}
                try:
                    rid = int(args.get("id"))
                except (TypeError, ValueError):
                    raise Refused("Which reminder number?")
                if rid not in ids:
                    raise Refused("I don't have a reminder with that number.")
                args["id"] = rid
                return f"Delete the reminder “{ids[rid]['text']}”"
            if name == "take_note" and not str(args.get("text", "")).strip():
                raise Refused("What should I write down?")
            return "Look at your life stats"
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

    def _do_top_processes(self, a):
        try:
            n = int(a.get("count") or 5)
        except (TypeError, ValueError):
            n = 5
        return procs.describe(procs.group(self.platform.list_processes()), n)

    def _do_close_program(self, a):
        self.platform.close_program(a["name"])
        return f"I asked {procs.key(a['name']).title()} to close."

    def _do_read_own_file(self, a):
        return self.selfedit.read(a["path"])

    def _do_propose_change(self, a):
        p = self.selfedit.propose(a["path"], a.get("old"), a.get("new"), a.get("reason"))
        if p["tests_ok"]:
            return (f"Change #{p['id']} to {p['path']} is ready: +{p['plus']} −{p['minus']} lines and all my tests pass. "
                    "Say apply it to go ahead (I'll ask you first).")
        return f"Change #{p['id']} failed my tests, so I won't use it. Test output:\n{p['tests']}"

    def _do_show_change(self, a):
        p = self.selfedit.load(a["id"])
        return f"Change #{p['id']} ({p['status']}) — {p['reason']}\n{p['diff'][:3000]}\nTests: {p['tests']}"

    def _do_apply_change(self, a):
        p = self.selfedit.apply(a["id"])
        return f"Applied change #{p['id']} to {p['path']}. Restart me (close and reopen my window) to use it."

    def _do_undo_change(self, a):
        p = self.selfedit.undo(a["id"])
        return f"Undid change #{p['id']} to {p['path']}. Restart me to go back to the old version."

    @staticmethod
    def _shortcut_url(url):
        """Shortcuts only ever reach devices on your own network (or this PC) over plain http(s)."""
        from urllib.parse import urlparse
        u = urlparse(str(url))
        host = u.hostname or ""
        if u.scheme not in ("http", "https") or "@" in u.netloc or not (host == "localhost" or net.is_private(host) or host == "127.0.0.1"):
            raise Refused("That shortcut isn't an address on your own network, so I won't run it.")
        return str(url)

    def _do_network_map(self, a):
        me = self.platform.local_ip()
        sub = net.lan(me)
        devices = net.parse_arp(self.platform.arp_table(sub))
        devices = [d for d in devices if d["ip"] != me]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(16) as ex:
            for d, nm in zip(devices[:60], ex.map(lambda d: self.platform.device_name(d["ip"]), devices[:60])):
                d["name"] = nm
        self.last_devices = devices
        return net.describe(devices, net.Known(self.cfg["data_dir"]).macs(), me)

    def _do_network_trust(self, a):
        net.Known(self.cfg["data_dir"]).trust([d["mac"] for d in self.last_devices])
        return f"Okay — I'll treat these {len(self.last_devices)} devices as yours and warn you about new ones."

    def _adb(self, *args):
        code, out = self.platform.adb(list(args), self.t.get("adb_path") or "adb")
        return code, out

    def _no_adb(self):
        return ("I can't find adb. Install Google's 'platform-tools', add it to PATH (or set tools.adb_path in settings.json), "
                "and turn on Wireless debugging on the phone.")

    def _do_phone_status(self, a):
        try:
            code, out = self._adb("devices")
            devs = [d for d in phone.parse_devices(out) if d[1] == "device"]
            if not devs:
                return "I can't see your phone. Turn on Wireless debugging, then tell me to connect to it (its address is shown there)."
            _, model = self._adb("shell", "getprop", "ro.product.model")
            _, batt = self._adb("shell", "dumpsys", "battery")
        except FileNotFoundError:
            raise Refused(self._no_adb())
        b = phone.parse_battery(batt)
        return f"Your {model.strip() or 'phone'} is connected." + (f" Battery {b['percent']}%, {b['state']}." if b else "")

    def _do_phone_connect(self, a):
        try:
            code, out = self._adb("connect", a["address"])
        except FileNotFoundError:
            raise Refused(self._no_adb())
        if code != 0 or "connected" not in out.lower() or "cannot" in out.lower() or "failed" in out.lower():
            raise Refused("I couldn't connect: " + out[:120])
        return f"Connected to your phone at {a['address']}."

    def _do_phone_open_app(self, a):
        _, pkg = phone.check_app(a["name"], self.t.get("phone_apps"))
        try:
            code, out = self._adb("shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
        except FileNotFoundError:
            raise Refused(self._no_adb())
        if code != 0 or "No activities found" in out or "Error" in out:
            raise Refused(f"I couldn't open {a['name']} on the phone. Is it connected and installed?")
        return f"Opened {a['name']} on your phone."

    def _do_run_shortcut(self, a):
        sc = {k.lower(): v for k, v in (self.t.get("shortcuts") or {}).items()}
        self.platform.http_get(self._shortcut_url(sc[a["name"]]))
        return f"Ran “{a['name']}”."

    def _do_search_documents(self, a):
        return self.knowledge.answer_context(a["query"])

    def _do_index_documents(self, a):
        return self.knowledge.update().describe()

    def _do_health_status(self, a):
        return self.companion.vitals.status()

    def _do_add_reminder(self, a):
        from .. import reminders as _r
        try:
            r = self.companion.reminders.add(a.get("text"), a.get("when"), a.get("repeat", "none"))
        except _r.Refused as e:
            raise Refused(str(e))
        d = datetime.fromisoformat(r["due"])
        return f"Okay, I'll remind you on {d:%A %d %B %Y} at {d:%H:%M}" + (f" (repeating {r['repeat']})" if r["repeat"] != "none" else "") + f". [#{r['id']}]"

    def _do_list_reminders(self, a):
        items = self.companion.reminders.upcoming(400)
        if not items:
            return "You have no upcoming reminders."
        return "Your reminders:\n" + "\n".join(
            f"#{i['id']} {datetime.fromisoformat(i['due']):%d %b %Y %H:%M} — {i['text']}" + (f" ({i['repeat']})" if i["repeat"] != "none" else "")
            for i in items[:20])

    def _do_remove_reminder(self, a):
        self.companion.reminders.remove(a["id"])
        return f"Deleted reminder #{a['id']}."

    def _do_take_note(self, a):
        from .. import reminders as _r
        try:
            self.companion.reminders.note(a.get("text"))
        except _r.Refused as e:
            raise Refused(str(e))
        return "Noted."

    def _do_list_notes(self, a):
        rows = self.companion.reminders.recent_notes(10, a.get("query", ""))
        return "Your notes:\n" + "\n".join(f"{r['at'][:16]} — {r['text']}" for r in rows) if rows else "I don't have any notes yet."

    def _do_screen_time(self, a):
        c = self.companion
        return " ".join(x for x in (c.usage.summary(), c.phone_usage.summary() if c.phone_usage.today else "") if x)

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
        always = always and p.name not in NO_ALWAYS
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
            res = self.approve(pid, always=True)
            return res["text"] + (" I won't ask about that again." if res.get("always") else
                                  " (I always ask about that kind of thing, though.)" if res["status"] == "done" else "")
        if YES.match(text):
            return self.approve(pid)["text"]
        if NO.match(text):
            return self.deny(pid)["text"]
        return None
