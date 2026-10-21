"""Choosing her voice by talking.  Say or type "change your voice" and she names her voices; then say a name
("Bella"), "the second one", "faster" or "slower", "keep it" or "never mind".  The same controls drive the
window's Voice tab.  Works with the Kokoro (offline) and Edge (online) voices; other engines have just one."""
import re

from . import config
from .voice import EDGE_VOICES, KOKORO_VOICES

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
WANTS = [re.compile(p) for p in (
    r"\b(?:change|switch|swap|pick|choose|select|different|another|new)\b.*\bvoices?\b",
    r"\bvoices?\b.*\b(?:change|switch|swap|different|another)\b",
    r"\b(?:which|what|list|show|tell me)\b.*\bvoices\b",
    r"\bwhich voice\b",
    r"\bvoices\b.*\b(?:do you have|available|can you (?:do|use))\b")]
NOT_ABOUT_HER = re.compile(r"\bvoice (?:command|commands|memo|message|mail|recording|typing|chat)\b")
SPEED = re.compile(r"\b(?:speak|talk|read|go)\b[a-z ]{0,20}\b(faster|slower|quicker)\b")
FASTER, SLOWER = re.compile(r"\b(faster|quicker|speed up|more quickly)\b"), re.compile(r"\b(slower|slow down|more slowly)\b")
KEEP = re.compile(r"\b(keep|that one|this one|i like|sounds? (?:good|great|nice)|perfect|yes|yeah|yep|sure|great|"
                  r"love it|nice|good|okay|ok|stay)\b")
DIRECT = re.compile(r"\b(?:use|keep|choose|pick|take|select|set|switch to|go with|i want|i'?ll take|i'?ll have)\b")
CANCEL = re.compile(r"\b(cancel|never ?mind|forget it|leave it|no thanks|no thank you|nothing|the same|go back|"
                    r"keep (?:my|the) (?:old|current|original|own))\b")


def friendly(name):
    """af_heart → Heart · en-US-AvaMultilingualNeural → Ava."""
    m = re.match(r"^[a-z]{2}-[A-Z]{2}-([A-Za-z]+?)(?:Multilingual)?Neural$", name)
    return m.group(1) if m else name.split("_", 1)[-1].capitalize()


def join_names(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class VoiceControl:
    """What can be changed right now: the voice and its speed. Safe when she has no natural voice."""

    def __init__(self, vk):
        self.vk = vk

    @property
    def engine(self):
        sp = self.vk.speaker
        return sp.engine if sp else None

    def kind(self):
        e = self.engine
        return e.name if e and e.name in ("kokoro", "edge") else None

    def catalog(self):
        return {"kokoro": KOKORO_VOICES, "edge": EDGE_VOICES}.get(self.kind(), {})

    def items(self):
        return [{"name": n, "who": friendly(n), "desc": d} for n, d in self.catalog().items()]

    def current(self):
        e, k = self.engine, self.kind()
        return None if not k else (e.spec if k == "kokoro" else e.voice)

    def speed(self):
        e, k = self.engine, self.kind()
        if k == "kokoro":
            return float(e.speed)
        if k == "edge":
            try:
                return 1 + int(str(e.rate).replace("%", "")) / 100
            except ValueError:
                return 1.0
        return 1.0

    def set_voice(self, name, persist=False, check=True):
        k, e, v = self.kind(), self.engine, self.vk.v
        if not k:
            raise ValueError("this voice engine has just one voice")
        if check and name not in self.catalog():
            raise ValueError(f"unknown voice '{name}'")
        if k == "kokoro":
            e.set_voice(name, v.get("speed", 1.0))
        else:
            e.voice = name
        if persist:
            key = "kokoro_voice" if k == "kokoro" else "edge_voice"
            v[key] = name
            config.save_setting("voice." + key, name)

    def set_speed(self, x):
        k, e, v = self.kind(), self.engine, self.vk.v
        if not k:
            raise ValueError("this voice engine has a fixed speed")
        x = round(max(0.7, min(1.4, float(x))), 2)
        v["speed"] = x
        config.save_setting("voice.speed", x)
        if k == "kokoro":
            e.set_voice(e.spec, x)
        else:
            e.rate = f"{round((x - 1) * 100):+d}%"
            config.save_setting("voice.edge_rate", e.rate)
        return x


class VoiceChooser:
    """The conversation about her voice. handle(text) → True if it was about her voice (and she has answered).
    `say(text, speak=True)` is how the host shows and speaks a line; `pending` is True while she waits for your answer."""

    def __init__(self, vk, say, user, milestone=None):
        self.vk, self.say, self.user, self.milestone = vk, say, user, milestone
        self.ctl = VoiceControl(vk)
        self.pending, self.original, self.trial = False, None, None

    # ---------------- entry ----------------
    def handle(self, text):
        t = " ".join(re.findall(r"[a-z0-9']+", text.lower()))
        if self.pending:
            return self._answer(t)
        if self._wants_voices(t):
            return self._start()
        m = SPEED.search(t)
        if m:
            return self._pace(m.group(1) in ("slower",), ask=False)
        return False

    @staticmethod
    def _wants_voices(t):
        return len(t) < 140 and not NOT_ABOUT_HER.search(t) and any(rx.search(t) for rx in WANTS)

    # ---------------- the dialogue ----------------
    def _start(self):
        if not self.ctl.kind():
            self.say("I only have one voice with this setup. Run setup_voice.bat to give me my natural voices, "
                     "and then I can choose from several.")
            return True
        if self.vk.mode == "off":
            self.say("My voice is muted right now. Say “voice on” first, then ask me again.", False)
            return True
        self.pending, self.original, self.trial = True, self.ctl.current(), None
        groups = {}
        for it in self.ctl.items():
            groups.setdefault(it["desc"].split(" · ")[0], []).append(it["who"])
        parts = [f"{g}: {join_names(n)}" for g, n in groups.items()]
        self.say(f"I have {len(self.ctl.items())} voices. " + ". ".join(parts) + f". Which would you like to hear, {self.user}?")
        return True

    def _answer(self, t):
        items, words = self.ctl.items(), t.split()
        by_word = {it["who"].lower(): it for it in items}
        pick = next((by_word[w] for w in words if w in by_word), None)
        if pick is None:
            nums = [ORDINALS.get(w) or (int(w) if w.isdigit() else None) for w in words]
            n = next((x for x in nums if x and 1 <= x <= len(items)), None)
            pick = items[n - 1] if n else None
        if pick:
            return self._choose(pick) if DIRECT.search(t) else self._try(pick)
        if FASTER.search(t) or SLOWER.search(t):
            return self._pace(bool(SLOWER.search(t)), ask=True)
        if CANCEL.search(t):
            self._restore()
            self.say("Okay, I'll keep my current voice.")
            return True
        if KEEP.search(t) and self.trial:
            return self._choose(self.trial_item())
        for group in {it["desc"].split(" · ")[0].lower(): it["desc"].split(" · ")[0] for it in items}:
            if group.split()[0] in words:
                names = [it["who"] for it in items if it["desc"].lower().startswith(group)]
                self.say(f"The {group.title()} voices are {join_names(names)}. Which one?")
                return True
        if KEEP.search(t):
            self.say("Which one would you like to hear? " + join_names([it["who"] for it in items]) + ".")
            return True
        self._restore()                                 # something else entirely: leave her voice as it was
        return False

    def trial_item(self):
        return next(it for it in self.ctl.items() if it["name"] == self.trial)

    def _try(self, item):
        if self.vk.speaker:
            self.vk.speaker.stop()
        self.ctl.set_voice(item["name"])
        self.trial = item["name"]
        self.say(f"Hi {self.user}, I'm Claire. Would you like me to sound like this? Say keep it, or name another voice.")
        return True

    def _choose(self, item):
        if self.vk.speaker:
            self.vk.speaker.stop()
        self.ctl.set_voice(item["name"], persist=True)
        self.pending, self.trial = False, None
        if self.milestone:
            self.milestone(f"Chose my voice: {item['name']}", f"{self.ctl.kind()} engine")
        self.say(f"Done. I'll sound like {item['who']} from now on.")
        return True

    def _pace(self, slower, ask):
        if not self.ctl.kind():
            self.say("My voice here can't change its speed. Run setup_voice.bat for my natural voice.")
            return True
        x = self.ctl.set_speed(self.ctl.speed() + (-0.1 if slower else 0.1))
        if self.vk.speaker:
            self.vk.speaker.stop()
        tail = " Say keep it, or name another voice." if ask else ""
        self.say(("A little slower." if slower else "A little faster.") + f" This is my pace now, {x:g}.{tail}")
        return True

    def _restore(self):
        if self.pending and self.trial and self.original:
            try:
                self.ctl.set_voice(self.original, check=False)
            except Exception:
                pass
        self.pending, self.trial = False, None
