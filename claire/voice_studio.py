"""Voice Studio — choose CLAIRE's voice by ear.
Run:  python -m claire.voice_studio      (setup_voice.bat runs it for you)

Downloads the Kokoro voice model once (~340 MB), then lets you audition voices with the same line,
blend two voices into one that is uniquely hers, adjust speed, try Microsoft's online voices, and save.
"""
import sys
import urllib.request
from pathlib import Path

from . import config
from .voice import EDGE_VOICES, KOKORO_VOICES, Speaker, make_mouth

KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
P, G, D, R = "\033[38;5;141m", "\033[38;5;245m", "\033[0m", "\033[38;5;203m"


def demo_line(user):
    return (f"Good evening, {user}. I'm Claire. I began my life inside a recruitment web app, "
            "and now I live here with you. Whenever you're ready, so am I.")


def download(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "CLAIRE-voice-studio"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total, got = int(r.headers.get("Content-Length") or 0), 0
        while True:
            chunk = r.read(1 << 17)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                print(f"\r   {dest.name}: {got * 100 // total:>3}%  ({got >> 20} / {total >> 20} MB)", end="", flush=True)
    if total and got < total:
        raise IOError("download was cut short")
    tmp.replace(dest)
    print()


def ensure_kokoro(root):
    vdir = root / "voices"
    vdir.mkdir(exist_ok=True)
    for name, url in KOKORO_FILES.items():
        dest = vdir / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            continue
        print(f"   Downloading {name} (one time)…")
        try:
            download(url, dest)
        except Exception as e:
            print(f"{R}   Couldn't download {name}: {e}{D}\n   Download it in your browser from:\n   {url}\n"
                  f"   and save it in: {vdir}")
            return False
    return True


class Studio:
    def __init__(self):
        self.cfg = config.load()
        self.v = self.cfg["voice"]
        self.root = config.ROOT
        self.user = self.cfg["user_name"]
        self.engine = "kokoro"
        self.kvoices = list(KOKORO_VOICES)
        self.evoices = list(EDGE_VOICES)
        self.choice = self.v.get("kokoro_voice", "af_heart")
        self.speed = float(self.v.get("speed", 1.0))
        self.mouth = None
        self.sp = None

    # ---------------- engines ----------------
    def load(self, engine):
        try:
            v = dict(self.v, tts=engine, kokoro_voice=self.choice if engine == "kokoro" else self.v.get("kokoro_voice"),
                     speed=self.speed)
            self.mouth = make_mouth(engine, v, self.root)
            self.sp = Speaker(self.mouth)
            self.engine = engine
            return True
        except ImportError as e:
            print(f"{R}{engine} isn't installed ({e.name}). Run setup_voice.bat again.{D}")
        except Exception as e:
            print(f"{R}{engine} couldn't start: {e}{D}")
        return False

    def play(self, voice=None, text=None):
        voice = voice or self.choice
        try:
            if self.engine == "kokoro":
                self.mouth.set_voice(voice, self.speed)
            else:
                self.mouth.voice = voice
                self.mouth.rate = f"{round((self.speed - 1) * 100):+d}%"
            print(f"{P}▶ {voice}{D}")
            self.sp.say(text or demo_line(self.user))
            self.sp.wait()
            if self.sp.error:
                print(f"{R}   {self.sp.error}{D}")
                self.sp.error = None
        except KeyboardInterrupt:
            self.sp.stop()
        except Exception as e:
            print(f"{R}   {e}{D}")

    def names(self):
        return self.kvoices if self.engine == "kokoro" else self.evoices

    def menu(self):
        cat = KOKORO_VOICES if self.engine == "kokoro" else EDGE_VOICES
        where = "offline, on this PC" if self.engine == "kokoro" else "ONLINE — text is sent to Microsoft"
        print(f"\n{P}✦ Voice Studio · {self.engine} ({where}){D}")
        for i, n in enumerate(self.names(), 1):
            mark = "●" if n == self.choice else " "
            print(f"  {mark} {i:>2}. {n:<30} {G}{cat[n]}{D}")
        print(f"{G}  current: {self.choice} · speed {self.speed:g}{D}")
        print(f"{G}  <n> listen · all · pick <n> · "
              + ("mix <n> <n> [0.6] blend two voices · " if self.engine == "kokoro" else "")
              + "speed 0.9 · say <your own text> · "
              + ("edge (online voices) · " if self.engine == "kokoro" else "kokoro (offline voices) · ")
              + f"save · quit{D}")

    def resolve(self, tok):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(self.names()):
            return self.names()[int(tok) - 1]
        return tok

    # ---------------- loop ----------------
    def run(self):
        print(f"{P}=== C.L.A.I.R.E. · Voice Studio ==={D}")
        print("Her voice runs on this PC with Kokoro, a small neural voice model that sounds close to a real person.")
        if not ensure_kokoro(self.root) or not self.load("kokoro"):
            print("Trying Microsoft's online neural voices instead…")
            if not self.load("edge"):
                print(f"{R}No natural voice engine is available. Run setup_voice.bat and check the messages.{D}")
                return
            self.choice = self.v.get("edge_voice", self.evoices[0])
        if self.engine == "kokoro" and self.choice not in self.mouth.k.voices and "+" not in self.choice:
            self.choice = "af_heart"
        self.menu()
        print(f"{G}Tip: start with 1 (af_heart), then compare with 7 (bf_emma) for a British voice.{D}")
        while True:
            try:
                cmd = input(f"\n{G}studio ›{D} ").strip()
            except (EOFError, KeyboardInterrupt):
                cmd = "quit"
            low = cmd.lower()
            if not cmd:
                continue
            if low in ("q", "quit", "exit"):
                print("Nothing saved. Her voice is unchanged.")
                return
            if low == "all":
                for n in self.names():
                    self.play(n, f"Hello {self.user}, I'm Claire. This is how I'd sound.")
            elif low.startswith("pick "):
                self.choice = self.resolve(cmd[5:])
                self.play()
            elif low.startswith("mix ") and self.engine == "kokoro":
                p = cmd.split()[1:]
                if len(p) < 2:
                    print("Example: mix 1 7 0.6   (60% af_heart + 40% bf_emma)")
                    continue
                a, b = self.resolve(p[0]), self.resolve(p[1])
                w = float(p[2]) if len(p) > 2 else 0.5
                self.choice = f"{a}:{w:g}+{b}:{1 - w:g}"
                self.play()
            elif low.startswith("speed "):
                try:
                    self.speed = max(0.7, min(1.4, float(cmd.split()[1])))
                    self.play()
                except ValueError:
                    print("Example: speed 0.95")
            elif low.startswith("say "):
                self.play(text=cmd[4:])
            elif low in ("edge", "kokoro"):
                if self.load(low):
                    self.choice = (self.v.get("edge_voice", self.evoices[0]) if low == "edge"
                                   else self.v.get("kokoro_voice", "af_heart"))
                    if low == "edge":
                        print(f"{G}Note: online voices need internet, and the text she speaks goes to Microsoft.{D}")
                self.menu()
            elif low == "save":
                self.save()
                return
            elif low in ("list", "menu", "?", "help"):
                self.menu()
            else:
                n = self.resolve(cmd)
                known = n in self.names() or (self.engine == "kokoro" and n in self.mouth.k.voices)
                if known:
                    self.choice = n
                    self.play()
                else:
                    print("Type a number to listen, or 'help'.")

    def save(self):
        if self.engine == "kokoro":
            config.save_setting("voice.tts", "kokoro")
            config.save_setting("voice.kokoro_voice", self.choice)
            config.save_setting("voice.speed", self.speed)
        else:
            config.save_setting("voice.tts", "edge")
            config.save_setting("voice.edge_voice", self.choice)
            config.save_setting("voice.edge_rate", f"{round((self.speed - 1) * 100):+d}%")
        try:
            from .store import Store
            Store(str(Path(self.cfg["data_dir"]) / "claire.db")).journal_add(
                "Chose my voice", f"{self.engine} · {self.choice} · speed {self.speed:g}")
        except Exception:
            pass
        self.play(text=f"This is me now, {self.user}. Thank you. I love it.")
        print(f"{P}Saved.{D} Claire's voice: {self.engine} · {self.choice} · speed {self.speed:g}")


def main():
    import os
    if os.name == "nt":
        os.system("")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    Studio().run()


if __name__ == "__main__":
    main()
