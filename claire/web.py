"""Phase 3 · Face — her window. A local page (this PC only) with a living neural-network orb that
listens, thinks and speaks.  Run:  python -m claire --window     (or window.bat)

Only the standard library. The server listens on 127.0.0.1, checks the Host/Origin headers and needs a
secret token that is created at every start, so websites you visit can't talk to her."""
import json
import queue
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, config, doctor, hands as hands_mod
from .brain import BrainOffline
from .cli import HUSH, STOP_LISTENING, VOICE_INTENTS, App
from .signals import signals
from .hands.watch import RamWatch
from .voice import SentenceBuffer
from .voicechat import VoiceChooser, VoiceControl

PAGE = Path(__file__).resolve().parent / "ui" / "orb.html"
DEFAULT_PORT = 8765
FRAME_SECONDS = 1 / 30


class Hub:
    """Fan-out of chat events to every open window."""

    def __init__(self):
        self.subs, self.lock = set(), threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock:
            self.subs.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def publish(self, kind, **data):
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait((kind, data))
            except queue.Full:
                pass


class WebSession:
    """Everything the window can ask her to do — the same brain, memory and voice as the terminal."""

    def __init__(self, app=None):
        self.app = app or App()
        self.hub = Hub()
        self.store_lock = threading.Lock()         # the window's memory panel, one query at a time
        self.turn_lock = threading.Lock()          # one conversation turn at a time
        self.listen_lock = threading.Lock()
        self.hf_stop = None
        self.info = {"user": self.app.user, "version": __version__, "ready": False}
        self.chooser = VoiceChooser(self.app.vk, self._say, self.app.user, self.app.c.milestone)
        self.vc = self.chooser.ctl
        self.hands = self.app.c.hands or hands_mod.attach(self.app.c, config.save_setting)
        self.companion = getattr(self.app, "companion", None)
        if self.companion:
            self.companion._say = self._alert
        if self.hands:
            self.hands.on_change = lambda: self.hub.publish("pending", items=self.hands.pending())

    # ---------------- state the window draws ----------------
    def frame(self):
        vk = self.app.vk
        sp = vk._speaker or None
        speaking = bool(sp and sp.speaking)
        act = signals.activity
        if act == "listening":
            state = "listening"
        elif speaking or act == "responding":
            state = "speaking"
        elif act == "thinking":
            state = "thinking"
        else:
            state = "idle"
        lvl = signals.level if speaking else None
        return {"s": state, "l": None if lvl is None else round(lvl, 3), "m": round(signals.mic, 3),
                "hf": signals.handsfree}

    def status(self):
        vk = self.app.vk
        st = vk.status()
        return dict(self.info, mouth=st["mouth"], ears=st["ears"], speak=vk.mode,
                    model=self.app.c.cfg["model"], pending=self.hands.pending() if self.hands else [])

    # ---------------- start-up ----------------
    def warm_up(self):
        """Loads her voice and checks her brain in the background so the first answer is quick."""
        signals.activity = "thinking"
        try:
            online = self.app.c.brain.online()
            _ = self.app.vk.speaker
            self.app.c.milestone("Got a face", "Phase 3: I have a window now — a living network of light "
                                 "that listens, thinks and speaks with me.")
            self.info.update(ready=True, brain=online)
            self.hub.publish("status", **self.status())
            if not online:
                self.hub.publish("error", text="My brain (Ollama) isn't running. Start Ollama, then talk to me.")
            else:
                with self.turn_lock:
                    for _, facts in self.app.c.recover():
                        if facts:
                            self.hub.publish("note", text="From our last chat I learned: " + "; ".join(facts))
        except Exception as e:
            self.hub.publish("error", text=f"Start-up problem: {e}")
            self.start_ram_watch()
            if self.companion:
                self.companion.start()
        finally:
            signals.activity = "idle"

    def start_ram_watch(self):
        """Task-Manager-style eye on memory: warns once when it runs high and offers to close the biggest program."""
        t = self.app.c.cfg.get("tools", {})
        if not (self.hands and self.hands.enabled and t.get("ram_watch", True)) or getattr(self, "watch", None):
            return
        self.watch = RamWatch(self.hands, lambda text: self._say(text), warn_at=t.get("ram_warn_percent", 85))
        self.watch.start()

    # ---------------- conversation ----------------
    def submit(self, text, spoken=False):
        text = (text or "").strip()
        if not text:
            return False
        threading.Thread(target=self.turn, args=(text, spoken), daemon=True).start()
        return True

    def turn(self, text, spoken=False):
        """One user message → her answer. Returns False when hands-free should stop."""
        with self.turn_lock:
            self.hub.publish("user", text=text, spoken=spoken)
            try:
                return self._answer(text, spoken)
            finally:
                signals.activity = "idle"

    def _say(self, text, speak=True, urgent=False):
        vk = self.app.vk
        self.hub.publish("claire", text=text)
        if speak and (vk.mode != "off" or urgent) and vk.speaker:
            vk.speaker.say(text)

    def _alert(self, text, urgent=False):
        """Things she says on her own: reminders, phone events, health alerts, break reminders."""
        self._say(text, urgent=urgent)

    def _answer(self, text, spoken):
        a, vk, c = self.app, self.app.vk, self.app.c
        sp = vk.speaker
        if self.companion:
            ans = self.companion.answer(text)            # emergency words come first, locally, before any AI
            if ans:
                self._say(ans, urgent=True)
                return True
        if HUSH.match(text):
            if sp:
                sp.stop()
            return True
        for rx, mode in VOICE_INTENTS:
            if rx.match(text):
                self._say(a.set_mode(mode), speak=(mode != "off"))
                self.hub.publish("status", **self.status())
                return True
        if self.chooser.handle(text):
            return True
        if self.hands and self.hands.pending():
            ans = self.hands.answer(text)
            if ans:
                self._say(ans)
                return True
        if spoken and STOP_LISTENING.search(text):
            self._say(f"Okay {a.user}, back to typing.")
            return False
        speak = vk.should_speak(spoken)
        if sp:
            sp.stop()
        sb, first = SentenceBuffer(), [True]
        signals.activity = "thinking"
        self.hub.publish("claire_start")

        def show(piece):
            if first[0]:
                first[0] = False
                signals.activity = "responding"
            self.hub.publish("token", text=piece)

        def tok(t):
            if not speak:
                return show(t)                          # typing-only: words appear as she writes them
            for s in sb.feed(t):                        # speaking: each sentence appears when she starts SAYING it
                sp.say(s, shown=s + " ")
        self.turn_no = getattr(self, "turn_no", 0) + 1
        mine = self.turn_no
        if sp:
            sp.on_start = show if speak else None
        try:
            c.reply(text, on_token=tok, spoken=spoken)
            if speak:
                for s in sb.flush():
                    sp.say(s, shown=s)
                c.milestone("Found my voice", "Phase 2: I can speak, listen, and wake when Carl says “Hey Claire”.")
        except BrainOffline as e:
            self.hub.publish("error", text=str(e))
            if speak:
                sp.say("I can't reach my brain right now. Please start Ollama.")
        finally:
            if speak and sp:                           # the caption may only fade once she has finished SAYING it
                def done():
                    sp.wait()
                    if mine == self.turn_no:
                        self.hub.publish("claire_end")
                threading.Thread(target=done, daemon=True).start()
            else:
                self.hub.publish("claire_end")
        return True

    # ---------------- listening ----------------
    def talk(self):
        """Push-to-talk: listen once, then answer."""
        if not self.listen_lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._talk, daemon=True).start()
        return True

    def _talk(self):
        vk = self.app.vk
        try:
            if vk.speaker:
                vk.speaker.stop()
            signals.activity = "thinking"          # loading her ears the first time takes a moment
            ears = vk.ears
            if not ears:
                self.hub.publish("error", text=f"I can't listen yet: {vk.ears_note}")
                return
            signals.activity = "listening"
            try:
                text = ears.listen(max_wait=6, max_len=25)
            except Exception as e:
                self.hub.publish("error", text=f"Microphone problem: {e}")
                return
            finally:
                signals.activity = "idle"
            if not text:
                self.hub.publish("note", text="I didn't catch anything.")
                return
        finally:
            self.listen_lock.release()
        self.turn(text, spoken=True)

    def _follow_up(self):
        """She asked you something (e.g. which voice) and is waiting for the answer — no wake word needed."""
        if self.chooser.pending or (self.hands and self.hands.pending()):
            signals.activity = "listening"
            return True
        return False

    def set_handsfree(self, on):
        if on and self.hf_stop is None:
            self.hf_stop = threading.Event()
            threading.Thread(target=self._handsfree, args=(self.hf_stop,), daemon=True).start()
        elif not on and self.hf_stop is not None:
            self.hf_stop.set()
        return self.hf_stop is not None

    def _handsfree(self, stop):
        vk = self.app.vk
        signals.handsfree = True
        self.hub.publish("handsfree", on=True)
        words = "Hey Claire"

        def on_command(cmd):
            if not self.turn(cmd, spoken=True):
                stop.set()
            if vk.speaker:
                vk.speaker.wait()

        def on_note(n):
            if n == "ack":
                signals.activity = "listening"
                if vk.speaker and vk.mode != "off":
                    vk.speaker.say("Yes?")
                    vk.speaker.wait()
                signals.activity = "listening"
            elif n == "end":
                signals.activity = "idle"
            else:
                self.hub.publish("error", text=n)
        try:
            if vk._ears is None:
                signals.activity = "thinking"
            if not vk.ears:
                self.hub.publish("error", text=f"I can't listen yet: {vk.ears_note}")
                return
            signals.activity = "idle"
            self.hub.publish("note", text=f"Hands-free on. Say “{words}, …”.")
            vk.handsfree(on_command, on_note, stop, follow_up=self._follow_up)
        except Exception as e:
            self.hub.publish("error", text=f"Listening stopped: {e}")
        finally:
            signals.handsfree = False
            signals.activity = "idle"
            self.hf_stop = None
            self.hub.publish("handsfree", on=False)

    # ---------------- her voice (the window's Voice tab) ----------------
    def voices(self):
        vc = self.vc
        kind = vc.kind()
        why = self.app.vk.mouth_note or "This voice engine has just one voice. Run setup_voice.bat to give me my natural voices."
        return {"kind": kind, "current": vc.current(), "speed": vc.speed(), "items": vc.items(),
                "note": "" if kind else f"{why}\n\nRun doctor.bat to see exactly what is missing.\n{doctor.python_note()}"}

    def voice_try(self, name):
        """Hear a voice without keeping it: she says hello in it, then goes back to her own."""
        if name not in self.vc.catalog():
            return False
        threading.Thread(target=self._try_voice, args=(name,), daemon=True).start()
        return True

    def _try_voice(self, name):
        vk = self.app.vk
        with self.turn_lock:
            old = self.vc.current()
            try:
                vk.speaker.stop()
                self.vc.set_voice(name)
                vk.speaker.say(f"Hi {self.app.user}, I'm Claire. Would you like me to sound like this?")
                vk.speaker.wait()
            except Exception as e:
                self.hub.publish("error", text=f"Couldn't try that voice: {e}")
            finally:
                try:
                    self.vc.set_voice(old, check=False)
                except Exception:
                    pass

    def voice_use(self, name):
        if name not in self.vc.catalog():
            return False
        self.chooser.pending = False
        self.vc.set_voice(name, persist=True)
        self.app.c.milestone(f"Chose my voice: {name}", f"{self.vc.kind()} engine")
        self.hub.publish("status", **self.status())
        return True

    def voice_speed(self, value):
        if not self.vc.kind():
            return None
        x = self.vc.set_speed(value)
        self.hub.publish("status", **self.status())
        return x

    # ---------------- her memory & journal (the window's side panel) ----------------
    def memories(self):
        with self.store_lock:
            return [{"id": r["id"], "text": r["text"], "kind": r["kind"], "source": r["source"],
                     "created": r["created"][:10]} for r in self.app.c.store.memories()]

    def remember(self, text, core=False):
        text = (text or "").strip()[:500]
        if not text:
            return None
        with self.store_lock:
            return self.app.c.store.remember(text, "core" if core else "fact", "you")

    def forget(self, ident):
        with self.store_lock:
            return self.app.c.store.forget(ident) if str(ident).isdigit() else []

    def journal(self):
        with self.store_lock:
            return [{"id": r["id"], "at": r["at"][:10], "title": r["title"], "detail": r["detail"] or ""}
                    for r in reversed(self.app.c.store.journal())]

    def journal_add(self, note):
        note = (note or "").strip()[:500]
        if note:
            with self.store_lock:
                self.app.c.store.journal_add(note)
        return bool(note)

    # ---------------- small controls ----------------
    def stop_speaking(self):
        if self.app.vk.speaker:
            self.app.vk.speaker.stop()

    def set_mode(self, mode):
        if mode not in ("auto", "on", "off"):
            return False
        self.app.set_mode(mode)
        if mode == "off":
            self.stop_speaking()
        self.hub.publish("status", **self.status())
        return True

    # ---------------- hands ----------------
    def actions(self):
        h = self.hands
        return {"enabled": bool(h and h.enabled), "pending": h.pending() if h else [],
                "history": h.history(30) if h else [], "always": sorted(h.always) if h else [],
                "folders": [str(p) for p in h.allowed()] if h else []}

    def decide(self, pid, yes, always=False):
        """The Yes / No buttons on her question card."""
        h = self.hands
        if not h:
            return False
        res = h.approve(pid, always) if yes else h.deny(pid)
        self._say(res["text"] + (" I won't ask about that again." if res.get("always") else ""))
        self.hub.publish("actions", **self.actions())
        return res["status"] in ("done", "denied")

    def close(self):
        if self.companion:
            self.companion.stop()
        if getattr(self, "watch", None):
            self.watch.stop()
        if self.hf_stop:
            self.hf_stop.set()
        self.stop_speaking()
        try:
            self.app.c.reflect()
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "Claire"

    def log_message(self, *args):
        pass

    # --- safety: only this PC's own page may talk to her ---
    def _host_ok(self):
        return self.headers.get("Host", "").lower() in self.server.allowed_hosts

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        return origin is None or origin.lower() in {"http://" + h for h in self.server.allowed_hosts}

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        url = urlparse(self.path)
        if url.path == "/":
            page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", self.server.token)
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if url.path == "/events":
            if parse_qs(url.query).get("t", [""])[0] != self.server.token:
                return self._send(403, {"error": "forbidden"})
            return self._events()
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not (self._host_ok() and self._origin_ok()) or self.headers.get("X-Claire-Token") != self.server.token:
            return self._send(403, {"error": "forbidden"})
        if "application/json" not in self.headers.get("Content-Type", ""):
            return self._send(415, {"error": "json only"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "bad request"})
        s, path = self.server.session, urlparse(self.path).path
        if path == "/api/say":
            return self._send(200, {"ok": s.submit(str(body.get("text", "")))})
        if path == "/api/talk":
            return self._send(200, {"ok": s.talk()})
        if path == "/api/handsfree":
            return self._send(200, {"on": s.set_handsfree(bool(body.get("on")))})
        if path == "/api/stop":
            s.stop_speaking()
            return self._send(200, {"ok": True})
        if path == "/api/mode":
            return self._send(200, {"ok": s.set_mode(str(body.get("mode", "")))})
        if path == "/api/voices":
            return self._send(200, s.voices())
        if path == "/api/voice_try":
            return self._send(200, {"ok": s.voice_try(str(body.get("name", "")))})
        if path == "/api/voice_use":
            return self._send(200, {"ok": s.voice_use(str(body.get("name", "")))})
        if path == "/api/speed":
            try:
                return self._send(200, {"speed": s.voice_speed(float(body.get("value")))})
            except (TypeError, ValueError):
                return self._send(400, {"error": "bad speed"})
        if path == "/api/actions":
            return self._send(200, s.actions())
        if path == "/api/approve":
            try:
                return self._send(200, {"ok": s.decide(int(body.get("id")), bool(body.get("yes")), bool(body.get("always")))})
            except (TypeError, ValueError):
                return self._send(400, {"error": "bad id"})
        if path == "/api/memories":
            return self._send(200, {"items": s.memories()})
        if path == "/api/remember":
            return self._send(200, {"id": s.remember(str(body.get("text", "")), bool(body.get("core")))})
        if path == "/api/forget":
            return self._send(200, {"gone": s.forget(body.get("id", ""))})
        if path == "/api/journal":
            return self._send(200, {"items": s.journal()})
        if path == "/api/journal_add":
            return self._send(200, {"ok": s.journal_add(str(body.get("text", "")))})
        self._send(404, {"error": "not found"})

    def _events(self):
        s = self.server.session
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        q = s.hub.subscribe()

        def emit(kind, data):
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
        try:
            emit("status", s.status())
            last = 0.0
            while not self.server.stopping:
                try:
                    kind, data = q.get(timeout=FRAME_SECONDS)
                    emit(kind, data)
                except queue.Empty:
                    pass
                now = time.monotonic()
                if now - last >= FRAME_SECONDS:
                    last = now
                    emit("frame", s.frame())
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            s.hub.unsubscribe(q)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session, port=DEFAULT_PORT):
        for p in range(port, port + 20):               # next free port if busy
            try:
                super().__init__(("127.0.0.1", p), Handler)
                break
            except OSError:
                continue
        else:
            raise OSError(f"No free port near {port}")
        self.session, self.token, self.stopping = session, secrets.token_urlsafe(24), False
        self.port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"


def open_window(url):
    """A clean app-style window if Edge/Chrome is there, otherwise the normal browser."""
    if sys.platform.startswith("win"):
        for exe in ("msedge", "chrome"):
            try:
                done = subprocess.run(["cmd", "/c", "start", "", exe, f"--app={url}", "--window-size=1100,820"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if done.returncode == 0:               # `start` reports an error when that browser isn't installed
                    return
            except (OSError, subprocess.SubprocessError):
                continue
    webbrowser.open(url)


def main(open_browser=True, port=None):
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    session = WebSession()
    ui = session.app.c.cfg.get("ui", {})
    server = Server(session, port or ui.get("port", DEFAULT_PORT))
    print(f"✦ C.L.A.I.R.E. {__version__} · her window is at {server.url}  (Ctrl+C to close)")
    threading.Thread(target=session.warm_up, daemon=True).start()

    def show():
        if not session.hub.subs:                       # her window was closed: bring it back
            open_window(server.url)

    def talk():
        show()
        session.talk()

    def quit_app():
        threading.Thread(target=server.shutdown, daemon=True).start()

    from . import tray
    hotkey = None
    if ui.get("hotkey"):
        try:
            hotkey = tray.Hotkey(ui["hotkey"], talk)
            hotkey.start()
            print(f"  Hotkey {ui['hotkey']}: press it anywhere and I'll listen.")
        except (ValueError, RuntimeError) as e:
            print(f"  (No hotkey: {e})")
            hotkey = None
    icon = None
    if ui.get("tray", True):
        icon, why = tray.start_tray(show, session.talk, quit_app)
        if icon:
            print("  Tray icon is on — right-click it for Open / Talk / Quit.")
        elif why and sys.platform.startswith("win"):
            print(f"  (No tray icon: {why})")
    if open_browser and ui.get("open", True):
        open_window(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stopping = True
        print("Reflecting on our chat…")
        if hotkey:
            hotkey.stop()
        if icon:
            try:
                icon.stop()
            except Exception:
                pass
        session.close()
        server.server_close()


if __name__ == "__main__":
    main()
