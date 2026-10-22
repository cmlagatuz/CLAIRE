"""Phase 2 · Voice — CLAIRE speaks, listens and wakes on "Hey Claire".

Mouth (best first):
  kokoro  — Kokoro-82M neural voice, offline, studio quality (default)
  edge    — Microsoft's online neural voices (Ava, Emma, Sonia…): optional, text goes to Microsoft
  piper   — older offline neural voice
  windows — built-in Windows voice (last resort, needs nothing)
Ears  : faster-whisper (offline) + sounddevice
Wake  : "whisper" (default, no training) or "openwakeword" (optional)
The Speaker renders the NEXT sentence while the current one plays, so she talks without gaps.
"""
import asyncio
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque
from pathlib import Path

from .signals import envelope, mic_level, signals

# ======================================================================
# text → speakable text
# ======================================================================
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]")


def clean_for_speech(text):
    t = str(text or "")
    t = re.sub(r"C\.L\.A\.I\.R\.E\.?|\bCLAIRE\b", "Claire", t)
    t = re.sub(r"```.*?```", " I've put the code on screen. ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://\S+", "the link on screen", t)
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\|.*\|\s*$", "", t, flags=re.M)
    t = re.sub(r"[*_#>|~]+", "", t)
    t = _EMOJI.sub("", t)
    t = t.replace("→", " to ").replace("·", ",").replace("&", " and ")
    return re.sub(r"\s+", " ", t).strip()


class SentenceBuffer:
    """Feeds streamed tokens, releases whole sentences so she can start talking early."""
    MIN = 14

    def __init__(self):
        self.buf = ""

    def feed(self, piece):
        self.buf += piece
        out = []
        while True:
            cut = None
            for m in re.finditer(r"[.!?](?=\s)|\n", self.buf):
                if m.end() >= self.MIN and self.buf[:m.end()].count("```") % 2 == 0:
                    cut = m.end()
                    break
            if cut is None:
                break
            s, self.buf = self.buf[:cut], self.buf[cut:]
            if s.strip():
                out.append(s.strip())
        return out

    def flush(self):
        s, self.buf = self.buf.strip(), ""
        return [s] if s else []


# ======================================================================
# audio playback
# ======================================================================
class Player:
    """Plays PCM or audio files; stop() works from any thread."""

    def __init__(self):
        self._stop = threading.Event()
        self._gen = 0

    def _meter(self, env, hop=0.03):
        """Publishes how loud she is right now (for the window) while the audio plays."""
        self._gen += 1
        gen, t0 = self._gen, time.monotonic()
        if not env:
            signals.level = None
            return

        def run():
            while gen == self._gen and not self._stop.is_set():
                i = int((time.monotonic() - t0) / hop)
                if i >= len(env):
                    break
                signals.level = env[i]
                time.sleep(0.02)
            if gen == self._gen:
                signals.level = 0.0
        threading.Thread(target=run, daemon=True).start()

    def _unmeter(self):
        self._gen += 1
        signals.level = 0.0

    def stop(self):
        self._stop.set()
        self._unmeter()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:
                pass

    LEAD, TAIL = 0.10, 0.45          # seconds of silence around every sentence

    def pcm(self, samples, rate):
        """Plays a sentence. Silence is added before and after: sound cards (especially Bluetooth) report 'finished'
        while the last ~0.3 s is still in their buffer, which used to cut off the final word."""
        self._stop.clear()
        import numpy as np
        samples = np.asarray(samples)
        pad = lambda secs: np.zeros(int(rate * secs), dtype=samples.dtype)       # noqa: E731
        samples = np.concatenate([pad(self.LEAD), samples, pad(self.TAIL)])
        try:
            import sounddevice as sd
            sd.play(samples, rate)
            self._meter(envelope(samples, rate))
            sd.wait()
            return
        except ImportError:
            pass
        import numpy as np
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(path, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
                w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            self.file(path)
        finally:
            _rm(path)

    def file(self, path):
        """wav or mp3."""
        self._stop.clear()
        self._meter(self._wav_envelope(path))
        if os.name == "nt":
            if str(path).lower().endswith(".wav"):
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
            else:
                self._mci(path)
            return
        for cmd in (["afplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"], ["mpg123", "-q"], ["aplay", "-q"]):
            try:
                p = subprocess.Popen(cmd + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                continue
            while p.poll() is None:
                if self._stop.is_set():
                    p.kill()
                time.sleep(0.05)
            return

    @staticmethod
    def _wav_envelope(path):
        """Loudness of a .wav file (mp3 can't be read without extra packages → None = window animates by itself)."""
        if not str(path).lower().endswith(".wav"):
            return None
        try:
            import numpy as np
            with wave.open(str(path), "rb") as w:
                if w.getsampwidth() != 2:
                    return None
                rate, ch = w.getframerate(), w.getnchannels()
                data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
            return envelope(data.reshape(-1, ch).mean(axis=1), rate)
        except Exception:
            return None

    def _mci(self, path):
        """Windows' own media player API — plays mp3 with nothing installed. Same thread opens & closes."""
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        alias = f"claire{threading.get_ident()}"
        buf = ctypes.create_unicode_buffer(64)
        mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
        mci(f"play {alias}", None, 0, None)
        try:
            while not self._stop.is_set():
                mci(f"status {alias} mode", buf, 64, None)
                if buf.value != "playing":
                    break
                time.sleep(0.04)
        finally:
            mci(f"close {alias}", None, 0, None)


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


# ======================================================================
# mouths — each has .label, say(text), stop(); fast ones also render(text) → (audio, rate)
# ======================================================================
KOKORO_VOICES = {   # the most natural English voices of Kokoro v1.0 (grades from its voice card)
    "af_heart": "American · warm, expressive — the most natural (A)",
    "af_bella": "American · bright, lively (A-)",
    "af_nicole": "American · soft, close, calm (B-)",
    "af_aoede": "American · smooth, mellow (C+)",
    "af_kore": "American · clear, confident (C+)",
    "af_sarah": "American · friendly, neutral (C+)",
    "bf_emma": "British · elegant, composed (B-)",
    "bf_isabella": "British · gentle, refined (C)",
    "bf_alice": "British · crisp (D)",
    "bf_lily": "British · light (D)",
}
EDGE_VOICES = {
    "en-US-AvaMultilingualNeural": "American · warm, natural, conversational",
    "en-US-EmmaMultilingualNeural": "American · cheerful, clear",
    "en-US-AriaNeural": "American · confident, polished",
    "en-US-JennyNeural": "American · friendly assistant",
    "en-GB-SoniaNeural": "British · poised, elegant",
    "en-GB-LibbyNeural": "British · bright, young",
    "en-AU-NatashaNeural": "Australian · warm",
    "en-PH-RosaNeural": "Filipino English · friendly",
}


def kokoro_lang(name):
    first = re.split(r"[:+]", name.strip())[0]
    return "en-gb" if first.startswith("b") else "en-us"


class KokoroMouth:
    name = "kokoro"

    def __init__(self, model, voices, voice="af_heart", speed=1.0):
        from kokoro_onnx import Kokoro
        self.k = Kokoro(str(model), str(voices))
        self.player = Player()
        self.set_voice(voice, speed)

    def style(self, spec):
        """'af_heart' or a blend 'af_heart:0.7+bf_emma:0.3' → name or blended style vector."""
        parts = [p.strip() for p in spec.split("+") if p.strip()]
        if len(parts) == 1 and ":" not in parts[0]:
            if parts[0] not in self.k.voices:
                raise ValueError(f"unknown Kokoro voice '{parts[0]}'")
            return parts[0]
        mix, total = None, 0.0
        for p in parts:
            n, _, w = p.partition(":")
            w = float(w or 1)
            v = self.k.get_voice_style(n.strip()) * w
            mix = v if mix is None else mix + v
            total += w
        return mix / total

    def set_voice(self, spec, speed=None):
        self.voice, self.spec = self.style(spec), spec
        self.lang = kokoro_lang(spec)
        if speed is not None:
            self.speed = max(0.5, min(2.0, float(speed)))
        self.label = f"Kokoro · {spec}" + (f" · speed {self.speed:g}" if self.speed != 1 else "")

    def render(self, text):
        return self.k.create(text, voice=self.voice, speed=self.speed, lang=self.lang)

    def play(self, audio):
        self.player.pcm(*audio)

    def say(self, text):
        self.play(self.render(text))

    def stop(self):
        self.player.stop()


class EdgeMouth:
    """Online. Needs internet; the text she speaks is sent to Microsoft's speech service."""
    name = "edge"

    def __init__(self, voice="en-US-AvaMultilingualNeural", rate="+0%", pitch="+0Hz"):
        import edge_tts  # noqa: F401
        self.voice, self.rate, self.pitch = voice, rate, pitch
        self.player = Player()
        self.label = f"Edge neural · {voice} (online)"

    def render(self, text):
        import edge_tts
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        comm = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        asyncio.run(comm.save(path))
        return path

    def play(self, path):
        try:
            self.player.file(path)
        finally:
            _rm(path)

    def discard(self, path):
        _rm(path)

    def say(self, text):
        self.play(self.render(text))

    def stop(self):
        self.player.stop()


class PiperMouth:
    name = "piper"

    def __init__(self, model_path):
        try:
            from piper import PiperVoice
        except ImportError:
            from piper.voice import PiperVoice
        self.voice = PiperVoice.load(str(model_path))
        self.player = Player()
        self.label = "Piper · " + Path(model_path).stem

    def render(self, text):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as w:
            if hasattr(self.voice, "synthesize_wav"):
                self.voice.synthesize_wav(text, w)
            else:
                self.voice.synthesize(text, w)
        return path

    def play(self, path):
        try:
            self.player.file(path)
        finally:
            _rm(path)

    def discard(self, path):
        _rm(path)

    def say(self, text):
        self.play(self.render(text))

    def stop(self):
        self.player.stop()


class WindowsMouth:
    name = "windows"
    label = "Windows voice (basic)"
    PS = ("[Console]::InputEncoding=[Text.Encoding]::UTF8;Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Gender -eq 'Female'}|select -First 1;"
          "if($v){$s.SelectVoice($v.VoiceInfo.Name)};$s.Rate=0;$s.Speak([Console]::In.ReadToEnd())")

    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows voice is only on Windows")
        self.proc = None

    def say(self, text):
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", self.PS],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.proc.communicate(text.encode("utf-8"))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


def _path(p, root):
    p = Path(p)
    return p if p.is_absolute() else Path(root) / p


def make_mouth(kind, v, root):
    if kind == "kokoro":
        m, vs = _path(v.get("kokoro_model", ""), root), _path(v.get("kokoro_voices", ""), root)
        if not (m.exists() and vs.exists()):
            raise FileNotFoundError("Kokoro voice files not found (run setup_voice)")
        return KokoroMouth(m, vs, v.get("kokoro_voice", "af_heart"), v.get("speed", 1.0))
    if kind == "edge":
        return EdgeMouth(v.get("edge_voice", "en-US-AvaMultilingualNeural"), v.get("edge_rate", "+0%"), v.get("edge_pitch", "+0Hz"))
    if kind == "piper":
        p = _path(v.get("piper_voice", ""), root)
        if not p.exists():
            raise FileNotFoundError("Piper voice file not found (run setup_voice)")
        return PiperMouth(p)
    if kind == "windows":
        return WindowsMouth()
    raise ValueError(f"unknown voice engine '{kind}'")


def pick_mouth(v, root):
    """Returns (engine or None, note about anything that was skipped)."""
    want = v.get("tts", "auto")
    order = ["kokoro", "piper", "windows"] if want == "auto" else [want, "windows"]
    notes = []
    for kind in dict.fromkeys(order):
        try:
            return make_mouth(kind, v, root), "; ".join(notes)
        except ImportError as e:
            notes.append(f"{kind}: not installed ({e.name}) — run setup_voice")
        except Exception as e:
            notes.append(f"{kind}: {e}")
    return None, "; ".join(notes) or "voice output is off"


class Speaker:
    """Speaks sentences in order. Engines that can render() are pipelined: the next sentence is
    prepared while the current one plays, so there are no pauses between sentences."""

    def __init__(self, engine):
        self.engine = engine
        self.q, self.aq = queue.Queue(), queue.Queue(maxsize=3)
        self.error, self.gen = None, 0
        self.on_start = None             # called with the sentence just as she begins to say it (the window shows it then)
        self.pipelined = hasattr(engine, "render") and hasattr(engine, "play")
        threading.Thread(target=self._render_loop, daemon=True).start()
        if self.pipelined:
            threading.Thread(target=self._play_loop, daemon=True).start()

    def _started(self, gen, shown):
        cb = self.on_start
        if cb and shown and gen == self.gen:
            try:
                cb(shown)
            except Exception:
                pass

    def _render_loop(self):
        while True:
            gen, text, shown = self.q.get()
            try:
                if gen != self.gen:
                    continue
                if not self.pipelined:
                    self._started(gen, shown)
                    if text:
                        self.engine.say(text)
                    continue
                audio = self.engine.render(text) if text else None
                if gen == self.gen:
                    self.aq.put((gen, audio, shown))
                else:
                    self._discard(audio)
            except Exception as e:
                self.error = e
            finally:
                self.q.task_done()

    def _play_loop(self):
        while True:
            gen, audio, shown = self.aq.get()
            try:
                if gen == self.gen:
                    self._started(gen, shown)
                    if audio is not None:
                        self.engine.play(audio)
                else:
                    self._discard(audio)
            except Exception as e:
                self.error = e
            finally:
                self.aq.task_done()

    def _discard(self, audio):
        if audio is not None and hasattr(self.engine, "discard"):
            self.engine.discard(audio)

    def say(self, text, shown=None):
        """Queue a sentence. `shown` (the original wording) goes to on_start when she begins saying it."""
        t = clean_for_speech(text)
        if t or shown:
            self.q.put((self.gen, t, shown))

    @property
    def speaking(self):
        return self.q.unfinished_tasks + self.aq.unfinished_tasks > 0

    def wait(self):
        self.q.join()
        self.aq.join()

    def stop(self):
        self.gen += 1                       # anything queued or rendering is now stale
        for qq in (self.q, self.aq):
            try:
                while True:
                    item = qq.get_nowait()
                    if qq is self.aq:
                        self._discard(item[1])
                    qq.task_done()
            except queue.Empty:
                pass
        self.engine.stop()


# ======================================================================
# ears
# ======================================================================
RATE, BLOCK = 16000, 480


def capture(blocks, rate=RATE, block=BLOCK, max_wait=6.0, max_len=15.0, silence=0.9,
            min_speech=0.25, calibrate=0.3, min_level=0.012):
    """Energy end-pointing: returns the spoken audio (float32 numpy) or None if nobody spoke."""
    import numpy as np
    bt = block / rate
    noise, pre = [], deque(maxlen=max(1, int(0.3 / bt)))
    started, buf, quiet, spoken, t, thr = False, [], 0.0, 0.0, 0.0, None
    for b in blocks:
        b = np.asarray(b, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(b * b)) + 1e-9)
        t += bt
        if not started:
            if t <= calibrate:
                noise.append(rms)
                pre.append(b)
                continue
            if thr is None:
                thr = max((float(np.median(noise)) if noise else 0.003) * 3.0, min_level)
            if rms > thr:
                started, buf, spoken = True, list(pre) + [b], bt
            else:
                pre.append(b)
                if t > max_wait:
                    return None
        else:
            buf.append(b)
            if rms > thr:
                quiet, spoken = 0.0, spoken + bt
            else:
                quiet += bt
            if quiet >= silence or len(buf) * bt >= max_len:
                break
    if not started or spoken < min_speech:
        return None
    return np.concatenate(buf)


class Ears:
    def __init__(self, model="base.en", language="en", device="cpu", mic=None):
        import sounddevice  # noqa: F401
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model, device=device, compute_type="int8")
        self.language = "en" if model.endswith(".en") else (None if language in ("", "auto") else language)
        self.mic = mic
        self.label = "Whisper · " + model

    def _blocks(self, stop_event=None):
        import sounddevice as sd
        with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, device=self.mic) as s:
            try:
                while not (stop_event and stop_event.is_set()):
                    data, _ = s.read(BLOCK)
                    signals.mic = mic_level(data)
                    yield data
            finally:
                signals.mic = 0.0

    def record(self, stop_event=None, **kw):
        return capture(self._blocks(stop_event), **kw)

    def transcribe(self, audio, prompt="Hey Claire."):
        segs, _ = self.model.transcribe(audio, language=self.language, beam_size=1, vad_filter=True,
                                        initial_prompt=prompt, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip()

    def listen(self, stop_event=None, **kw):
        a = self.record(stop_event, **kw)
        return self.transcribe(a) if a is not None else ""


# ======================================================================
# wake word
# ======================================================================
def wake_regex(names):
    alts = "|".join(sorted({re.escape(n.lower()) for n in names}, key=len, reverse=True))
    return re.compile(r"^\W*(?:(?:hey|hi|hello|okay|ok|yo|oi)\W+)?(?:" + alts + r")\b[\W]*(.*)$", re.I | re.S)


def split_wake(text, rx):
    m = rx.match(text or "")
    return (True, m.group(1).strip()) if m else (False, "")


class OpenWakeWord:
    def __init__(self, model, threshold=0.5, mic=None):
        from openwakeword.model import Model
        self.m = Model(wakeword_models=[model], inference_framework="onnx")
        self.threshold, self.mic = threshold, mic

    def wait(self, stop_event):
        import numpy as np
        import sounddevice as sd
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=1280, device=self.mic) as s:
            while not stop_event.is_set():
                data, _ = s.read(1280)
                if max(self.m.predict(np.asarray(data).reshape(-1)).values()) >= self.threshold:
                    self.m.reset()
                    return True
        return False


# ======================================================================
# everything together
# ======================================================================
SPEAK_MODES = ("auto", "on", "off")


class VoiceKit:
    def __init__(self, cfg, root):
        self.cfg, self.root = cfg, root
        self.v = cfg["voice"]
        self._speaker, self._ears, self._wake = None, None, None
        self.mouth_note = self.ears_note = ""
        self.rx = wake_regex(self.v.get("wake_words", ["claire"]))

    @property
    def speaker(self):
        if self._speaker is None and self.v.get("enabled", True):
            eng, self.mouth_note = pick_mouth(self.v, self.root)
            self._speaker = Speaker(eng) if eng else False
        return self._speaker or None

    def reload_mouth(self):
        if self._speaker:
            self._speaker.stop()
        self._speaker = None
        return self.speaker

    @property
    def mode(self):
        m = self.v.get("speak", "auto")
        return m if m in SPEAK_MODES else "auto"

    def set_mode(self, m):
        self.v["speak"] = m

    def should_speak(self, spoken):
        return bool(self.speaker) and (self.mode == "on" or (self.mode == "auto" and spoken))

    @property
    def ears(self):
        if self._ears is None and self.v.get("enabled", True):
            try:
                self._ears = Ears(self.v.get("stt_model", "base.en"), self.v.get("language", "en"),
                                  self.v.get("device", "cpu"), self.v.get("mic"))
            except ImportError as e:
                self.ears_note = f"speech recognition not installed ({e.name}) — run setup_voice"
                self._ears = False
            except Exception as e:
                self.ears_note = f"microphone/speech model problem: {e}"
                self._ears = False
        return self._ears or None

    def wake_engine(self):
        if self.v.get("wake_engine", "whisper") != "openwakeword":
            return None
        if self._wake is None:
            try:
                self._wake = OpenWakeWord(self.v.get("wake_model", "hey_jarvis"), self.v.get("wake_threshold", 0.5),
                                          self.v.get("mic"))
            except Exception as e:
                self.ears_note = f"openWakeWord unavailable ({e}); using Whisper wake instead"
                self._wake = False
        return self._wake or None

    def status(self):
        import importlib.util as iu
        sp = self.speaker
        if self._ears:
            ears = self._ears.label
        elif self._ears is False or not self.v.get("enabled", True):
            ears = "off (" + (self.ears_note or "disabled") + ")"
        else:
            miss = [m for m in ("faster_whisper", "sounddevice", "numpy") if iu.find_spec(m) is None]
            ears = ("off (not installed: " + ", ".join(miss) + " — run setup_voice)") if miss else \
                   "Whisper · " + self.v.get("stt_model", "base.en") + " (loads on first use)"
        mouth = sp.engine.label if sp else "off"
        if self.mouth_note:
            mouth += "   [skipped: " + self.mouth_note + "]"
        return {"mouth": mouth, "ears": ears, "speak": self.mode, "wake": self.v.get("wake_engine", "whisper")}

    def handsfree(self, on_command, on_note, stop_event, follow_up=None):
        """`follow_up()` → True while she is waiting for your answer: she then listens again without the wake word."""
        ears = self.ears
        if not ears:
            on_note("I can't listen: " + self.ears_note)
            return
        oww = self.wake_engine()
        while not stop_event.is_set():
            if self._speaker:
                self._speaker.wait()
            if oww:
                if not oww.wait(stop_event):
                    break
                heard, cmd = True, ""
            else:
                audio = ears.record(stop_event, max_wait=3600, max_len=12, silence=0.8)
                if audio is None:
                    continue
                heard, cmd = split_wake(ears.transcribe(audio), self.rx)
            if not heard:
                continue
            if not cmd:
                on_note("ack")
                cmd = ears.listen(stop_event, max_wait=6, max_len=20)
            if cmd:
                on_command(cmd)
                while follow_up and follow_up() and not stop_event.is_set():
                    if self._speaker:
                        self._speaker.wait()
                    more = ears.listen(stop_event, max_wait=8, max_len=20)
                    if not more:
                        on_note("end")             # no answer: the next command needs "Hey Claire" again
                        break
                    on_command(more)
            else:
                on_note("end")                     # she was called but nothing followed
