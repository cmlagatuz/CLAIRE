"""Terminal chat with CLAIRE.  Run:  python -m claire
Voice: press Enter on an empty line to talk · /handsfree for "Hey Claire" · /voice for settings."""
import os
import re
import sys
import threading

from . import __version__, config
from .brain import BrainOffline
from .core import Claire
from .voice import EDGE_VOICES, KOKORO_VOICES, SentenceBuffer, VoiceKit

P, G, D, R = "\033[38;5;141m", "\033[38;5;245m", "\033[0m", "\033[38;5;203m"
HELP = """Talk
  type a message · press Enter on an empty line to SPEAK (push-to-talk)
  /handsfree           listen for "Hey Claire …" (Ctrl+C or say "stop listening" to return)
Voice
  /voice               status · /voice on | off | auto  (auto = answers aloud when you spoke)
  /voice list          her voices · /voice try <name> · /voice use <name>
  /voice speed 0.95    slower/faster · /voice engine kokoro | edge | windows
  /voice studio        open the Voice Studio · /voice test · /mute · /unmute · /stop
  /mic                 list microphones · /mic <number> to choose
Memory
  /remember <fact>     save something   (/remember! <fact> = core fact about you)
  /forget <id|words>   forget a memory · /memories  list them
  /journal [note]      show my journal, or add an entry
Session
  /new  finish this chat (I reflect & learn) and start fresh · /model [name] · /status · /help · /quit"""

VOICE_INTENTS = [
    (re.compile(r"^(?:please )?(mute|be quiet|stop talking|voice off|silence)\b", re.I), "off"),
    (re.compile(r"^(?:please )?(unmute|voice on|talk to me|speak to me|read (?:it )?aloud)\b", re.I), "on"),
    (re.compile(r"^voice auto\b", re.I), "auto"),
]
STOP_LISTENING = re.compile(r"\b(stop listening|go to sleep|that'?s all|goodbye|good night|bye)\b", re.I)
HUSH = re.compile(r"^(stop|cancel|shut up|enough|never ?mind)\W*$", re.I)


class App:
    def __init__(self):
        self.c = Claire()
        self.vk = VoiceKit(self.c.cfg, config.ROOT)
        self.user = self.c.cfg["user_name"]

    def say_line(self, text, speak=True):
        print(f"{P}Claire ›{D} {text}")
        if speak and self.vk.mode != "off" and self.vk.speaker:
            self.vk.speaker.say(text)

    def set_mode(self, m):
        self.vk.set_mode(m)
        config.save_setting("voice.speak", m)
        return {"on": "Voice on — I'll read every answer aloud.",
                "off": "Okay, I'll stay quiet. Say or type “talk to me” to hear me again.",
                "auto": "Voice on auto — I'll answer aloud when you speak to me."}[m]

    def handle(self, text, spoken=False):
        """Returns False when the hands-free loop should stop."""
        sp = self.vk.speaker
        if HUSH.match(text):
            if sp:
                sp.stop()
            return True
        for rx, mode in VOICE_INTENTS:
            if rx.match(text):
                self.say_line(self.set_mode(mode), speak=(mode != "off"))
                return True
        if spoken and STOP_LISTENING.search(text):
            self.say_line(f"Okay {self.user}, back to typing.")
            return False
        speak = self.vk.should_speak(spoken)
        if sp:
            sp.stop()
        sb = SentenceBuffer()

        def tok(t):
            print(t, end="", flush=True)
            if speak:
                for s in sb.feed(t):
                    sp.say(s)
        print(f"{P}Claire ›{D} ", end="", flush=True)
        try:
            self.c.reply(text, on_token=tok, spoken=spoken)
            print()
            if speak:
                for s in sb.flush():
                    sp.say(s)
                if self.c.milestone("Found my voice", "Phase 2: I can speak, listen, and wake when Carl says “Hey Claire”."):
                    print(f"{G}(Journal: Found my voice){D}")
        except BrainOffline as e:
            print(f"{R}{e}{D}")
            if speak:
                sp.say("I can't reach my brain right now. Please start Ollama.")
        return True

    # ---------------- listening ----------------
    def push_to_talk(self):
        if self.vk.speaker:
            self.vk.speaker.stop()
        if self.vk._ears is None:
            print(f"{G}Loading my ears… (first time downloads the speech model){D}")
        ears = self.vk.ears
        if not ears:
            print(f"{R}I can't listen yet: {self.vk.ears_note}{D}")
            return
        print(f"{G}🎤 Listening… speak now{D}")
        try:
            text = ears.listen(max_wait=6, max_len=25)
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"{R}Microphone problem: {e}{D}")
            return
        if not text:
            print(f"{G}(I didn't catch anything){D}")
            return
        print(f"{G}{self.user} 🎤 ›{D} {text}")
        self.handle(text, spoken=True)

    def handsfree(self):
        if self.vk._ears is None:
            print(f"{G}Loading my ears…{D}")
        if not self.vk.ears:
            print(f"{R}I can't listen yet: {self.vk.ears_note}{D}")
            return
        stop = threading.Event()
        words = "Hey Claire" if self.vk.v.get("wake_engine") != "openwakeword" else f"your wake word ({self.vk.v.get('wake_model')})"
        print(f"{P}✦ Hands-free.{D} Say “{words}, …”. {G}Ctrl+C or “stop listening” to go back to typing.{D}")

        def on_command(cmd):
            print(f"{G}{self.user} 🎤 ›{D} {cmd}")
            if not self.handle(cmd, spoken=True):
                stop.set()
            if self.vk.speaker:
                self.vk.speaker.wait()

        def on_note(n):
            if n == "ack":
                print(f"{G}(yes?){D}")
                if self.vk.speaker and self.vk.mode != "off":
                    self.vk.speaker.say("Yes?")
                    self.vk.speaker.wait()
            elif n != "end":
                print(f"{R}{n}{D}")
        try:
            self.vk.handsfree(on_command, on_note, stop)
        except KeyboardInterrupt:
            stop.set()
            print(f"\n{G}Back to typing.{D}")
        except Exception as e:
            print(f"{R}Listening stopped: {e}{D}")

    # ---------------- voice choice ----------------
    def hear(self, text=None):
        sp = self.vk.speaker
        if not sp:
            print(f"{R}No voice available: {self.vk.mouth_note}{D}")
            return
        sp.say(text or f"Hello {self.user}. This is my voice. I was born in a web app, and now I can talk.")
        sp.wait()
        if sp.error:
            print(f"{R}Voice error: {sp.error}{D}")
            sp.error = None

    def voice_cmd(self, arg):
        vk, v = self.vk, self.vk.v
        sub, _, rest = arg.partition(" ")
        sub, rest = sub.lower(), rest.strip()
        eng = vk.speaker.engine if vk.speaker else None
        if sub in ("on", "off", "auto"):
            print(self.set_mode(sub))
        elif sub == "test":
            self.hear()
        elif sub == "list":
            kind = eng.name if eng else v.get("tts")
            cat = EDGE_VOICES if kind == "edge" else KOKORO_VOICES
            cur = v.get("edge_voice") if kind == "edge" else v.get("kokoro_voice")
            for n, d in cat.items():
                print(f"  {'●' if n == cur else ' '} {n:<30} {G}{d}{D}")
            print(f"{G}  /voice try <name> to listen · /voice use <name> to keep · /voice studio to compare & blend{D}")
        elif sub in ("try", "use"):
            if not rest:
                print("Which voice? /voice list")
                return
            if not eng or eng.name not in ("kokoro", "edge"):
                print("Natural voices aren't active yet — run setup_voice.bat (or /voice engine kokoro).")
                return
            old = eng.spec if eng.name == "kokoro" else eng.voice
            try:
                if eng.name == "kokoro":
                    eng.set_voice(rest, v.get("speed", 1.0))
                else:
                    eng.voice = rest
                self.hear(f"Hi {self.user}, I'm Claire. Would you like me to sound like this?")
            except Exception as e:
                print(f"{R}{e}{D}")
                sub = "try"
            if sub == "use":
                key = "voice.kokoro_voice" if eng.name == "kokoro" else "voice.edge_voice"
                v[key.split(".")[1]] = rest
                config.save_setting(key, rest)
                self.c.milestone(f"Chose my voice: {rest}", f"{eng.name} engine")
                print(f"Saved — I'll speak as {rest} from now on.")
            else:
                if eng.name == "kokoro":
                    eng.set_voice(old, v.get("speed", 1.0))
                else:
                    eng.voice = old
        elif sub == "speed":
            try:
                x = max(0.7, min(1.4, float(rest)))
            except ValueError:
                print("Example: /voice speed 0.95")
                return
            v["speed"] = x
            config.save_setting("voice.speed", x)
            if eng and eng.name == "kokoro":
                eng.set_voice(eng.spec, x)
            elif eng and eng.name == "edge":
                eng.rate = f"{round((x - 1) * 100):+d}%"
                config.save_setting("voice.edge_rate", eng.rate)
            self.hear("This is my new pace. How does it sound?")
        elif sub == "engine":
            if rest not in ("kokoro", "edge", "piper", "windows", "auto"):
                print("Engines: kokoro (offline, natural) · edge (online, natural) · piper · windows · auto")
                return
            v["tts"] = rest
            config.save_setting("voice.tts", rest)
            vk.reload_mouth()
            st = vk.status()
            print(f"Voice: {st['mouth']}")
            if rest == "edge":
                print(f"{G}Note: Edge voices need internet, and the text I speak is sent to Microsoft.{D}")
            self.hear()
        elif sub == "studio":
            if vk._speaker:
                vk._speaker.stop()
            from . import voice_studio
            voice_studio.main()
            self.c.cfg.update(config.load())
            vk.v = self.c.cfg["voice"]
            vk.reload_mouth()
            print(f"Voice: {vk.status()['mouth']}")
        else:
            for k, val in vk.status().items():
                print(f"  {k:<6} {val}")

    # ---------------- main loop ----------------
    def run(self):
        c = self.c
        print(f"{P}✦ C.L.A.I.R.E. {__version__}{D}  {G}· Lagatuz Labs · model {c.cfg['model']} · /help{D}")
        st = self.vk.status()
        print(f"{G}Voice: {st['mouth']} · speak {st['speak']} · Enter on an empty line to talk{D}")
        if self.vk.speaker and self.vk.speaker.engine.name == "windows":
            print(f"{G}Tip: run setup_voice.bat to give me my natural voice.{D}")
        if not c.brain.online():
            print(f"{R}My brain (Ollama) isn't running. Start Ollama, then talk to me.{D}")
        else:
            for _, facts in c.recover():
                if facts:
                    print(f"{G}(From our last chat I learned: {'; '.join(facts)}){D}")
        while True:
            try:
                text = input(f"\n{G}{self.user} ›{D} ").strip()
            except (EOFError, KeyboardInterrupt):
                text = "/quit"
            if not text:
                self.push_to_talk()
                continue
            if text.startswith("/"):
                if self.command(text):
                    break
                continue
            self.handle(text)

    def command(self, text):
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        c, s, vk = self.c, self.c.store, self.vk
        if cmd in ("/quit", "/exit", "/bye"):
            print(f"{G}Reflecting on our chat…{D}")
            _, facts = c.reflect()
            if facts:
                print(f"{G}Learned: {'; '.join(facts)}{D}")
            self.say_line(f"Goodbye, {self.user}.", speak=vk.mode == "on")
            if vk._speaker:
                vk._speaker.wait()
            return True
        if cmd == "/help":
            print(HELP)
        elif cmd == "/voice":
            self.voice_cmd(arg)
        elif cmd == "/mute":
            print(self.set_mode("off"))
        elif cmd == "/unmute":
            print(self.set_mode("on"))
        elif cmd == "/stop":
            if vk.speaker:
                vk.speaker.stop()
        elif cmd == "/listen":
            self.push_to_talk()
        elif cmd == "/handsfree":
            self.handsfree()
        elif cmd == "/mic":
            try:
                import sounddevice as sd
                if arg.isdigit():
                    vk.v["mic"] = int(arg)
                    config.save_setting("voice.mic", int(arg))
                    vk._ears = None
                    print(f"Microphone set to #{arg}.")
                else:
                    for i, d in enumerate(sd.query_devices()):
                        if d["max_input_channels"] > 0:
                            print(f"  #{i:<3} {d['name']}")
            except ImportError:
                print("Voice packages aren't installed yet — run setup_voice.")
        elif cmd in ("/remember", "/remember!"):
            if not arg:
                print("What should I remember?")
            else:
                i = s.remember(arg, "core" if cmd.endswith("!") else "fact", "you")
                print(f"Remembered (#{i})." if i else "I already know that.")
        elif cmd == "/forget":
            gone = s.forget(arg) if arg else []
            print("Forgotten: " + "; ".join(gone) if gone else "I couldn't find that memory. Use /memories to see the numbers.")
        elif cmd == "/memories":
            rows = s.memories()
            print("\n".join(f"#{r['id']:<4}{'★ ' if r['kind'] == 'core' else '  '}{r['text']}  {G}({r['source']}, {r['created'][:10]}){D}"
                            for r in rows) or "No memories yet.")
        elif cmd == "/journal":
            if arg:
                s.journal_add(arg)
                print("Added to my journal.")
            for r in s.journal():
                print(f"{G}{r['at'][:10]}{D}  {r['title']}" + (f"\n            {G}{r['detail']}{D}" if r["detail"] else ""))
        elif cmd == "/new":
            summary, facts = c.new_chat()
            print(f"{G}Saved: {summary or '—'}" + (f" · learned {len(facts)} thing(s)" if facts else "") + f"{D}\nFresh chat.")
        elif cmd == "/model":
            if arg:
                c.brain.model = c.cfg["model"] = arg
                config.save_setting("model", arg)
                print(f"Model set to {arg}.")
            else:
                print(f"Model: {c.cfg['model']}")
                try:
                    print("Downloaded: " + ", ".join(c.brain.models()))
                except Exception:
                    pass
        elif cmd == "/status":
            st = vk.status()
            print(f"Brain: {'online' if c.brain.online() else 'OFFLINE'} · model {c.cfg['model']} · "
                  f"{len(s.memories())} memories · {len(s.journal())} journal entries\n"
                  f"Voice: {st['mouth']}\nEars: {st['ears']} · speak {st['speak']} · wake {st['wake']}\n"
                  f"Data: {c.cfg['data_dir']}")
        else:
            print("Unknown command. /help")
        return False


def main():
    if os.name == "nt":
        os.system("")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    App().run()
