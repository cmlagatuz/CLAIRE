"""Phase 2 · Voice acceptance tests — no microphone, speakers or models needed."""
import json
import sys
import tempfile
import threading
import types
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claire import cli, config, voice                     # noqa: E402
from claire.voice import (SentenceBuffer, Speaker, VoiceKit, capture, clean_for_speech,  # noqa: E402
                          split_wake, wake_regex)
try:
    from tests.test_phase1 import FakeBrain, make          # noqa: E402
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_phase1 import FakeBrain, make                # noqa: E402

try:
    import numpy as np
except ImportError:                                        # numpy arrives with setup_voice
    np = None


class FakeMouth:
    name, label = "fake", "Fake voice"

    def __init__(self):
        self.said, self.stopped = [], 0

    def say(self, t):
        self.said.append(t)

    def stop(self):
        self.stopped += 1


def vcfg(**kw):
    c = json.loads(json.dumps(config.DEFAULTS))
    c["voice"].update(kw)
    return c


class SpeechText(unittest.TestCase):
    def test_clean_for_speech(self):
        t = clean_for_speech("**C.L.A.I.R.E.** says hi 🌙\n- item one\n```py\nx=1\n```\nSee [docs](https://x.y) or https://a.b/c")
        self.assertEqual(t, "Claire says hi item one I've put the code on screen. See docs or the link on screen")

    def test_sentences_stream_early_and_safely(self):
        sb, out = SentenceBuffer(), []
        for tok in "Hello Carl, good news. The time is 3.45 pm! Code: ```a. b. c.``` is shown. Bye".split(" "):
            out += sb.feed(tok + " ")
        out += sb.flush()
        self.assertEqual(out[0], "Hello Carl, good news.")
        self.assertEqual(out[1], "The time is 3.45 pm!")              # 3.45 not split
        self.assertTrue(any("```a. b. c.```" in s for s in out))      # code kept whole
        self.assertEqual(out[-1], "Bye")


class Mouth(unittest.TestCase):
    def test_speaker_order_and_stop(self):
        m = FakeMouth()
        sp = Speaker(m)
        for s in ("One.", "Two.", "**Three.**"):
            sp.say(s)
        sp.wait()
        self.assertEqual(m.said, ["One.", "Two.", "Three."])
        sp.stop()
        self.assertEqual(m.stopped, 1)
        self.assertFalse(sp.speaking)

    def test_piper_engine_both_api_versions(self):
        played = []
        old_play = voice._play_wav
        voice._play_wav = lambda p, *a: played.append(wave.open(p).getnframes())
        try:
            for api in ("synthesize_wav", "synthesize"):
                class V:
                    @staticmethod
                    def load(path):
                        return V()
                def synth(self, text, w):
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\0\0" * 100)
                setattr(V, api, synth)
                sys.modules["piper"] = types.SimpleNamespace(PiperVoice=V)
                tmp = Path(tempfile.mkdtemp()) / "v.onnx"
                tmp.write_bytes(b"x")
                eng, note = voice.pick_mouth({"tts": "piper", "piper_voice": str(tmp)}, "/")
                self.assertEqual(eng.name, "piper", note)
                eng.say("hello")
            self.assertEqual(played, [100, 100])
        finally:
            voice._play_wav = old_play
            sys.modules.pop("piper", None)

    def test_missing_voice_explains(self):
        eng, note = voice.pick_mouth({"tts": "piper", "piper_voice": "nope.onnx"}, tempfile.mkdtemp())
        self.assertIsNone(eng)
        self.assertIn("setup_voice", note)

    def test_speak_modes(self):
        vk = VoiceKit(vcfg(speak="auto"), "/")
        vk._speaker = Speaker(FakeMouth())
        self.assertTrue(vk.should_speak(True))
        self.assertFalse(vk.should_speak(False))
        vk.set_mode("on");  self.assertTrue(vk.should_speak(False))
        vk.set_mode("off"); self.assertFalse(vk.should_speak(True))


@unittest.skipIf(np is None, "numpy not installed yet (setup_voice installs it)")
class Ears(unittest.TestCase):
    R, B = 16000, 480

    def blocks(self, *parts):
        out = []
        rng = np.random.default_rng(1)
        for secs, amp in parts:
            n = int(secs * self.R)
            sig = (np.sin(np.arange(n) * 2 * np.pi * 220 / self.R) * amp if amp > 0.01
                   else rng.normal(0, 0.002, n)).astype(np.float32)
            out.append(sig)
        a = np.concatenate(out)
        return [a[i:i + self.B] for i in range(0, len(a) - self.B + 1, self.B)]

    def test_captures_one_utterance(self):
        a = capture(self.blocks((0.6, 0), (1.0, 0.2), (1.5, 0)))
        self.assertIsNotNone(a)
        self.assertTrue(1.0 <= len(a) / self.R <= 2.4)

    def test_silence_times_out(self):
        self.assertIsNone(capture(self.blocks((3, 0)), max_wait=2))

    def test_click_is_ignored(self):
        self.assertIsNone(capture(self.blocks((0.6, 0), (0.06, 0.3), (1.5, 0))))


class Wake(unittest.TestCase):
    rx = wake_regex(config.DEFAULTS["voice"]["wake_words"])

    def test_wake_phrases(self):
        self.assertEqual(split_wake("Hey Claire, what time is it?", self.rx), (True, "what time is it?"))
        self.assertEqual(split_wake("Clare.", self.rx), (True, ""))
        self.assertEqual(split_wake("okay Clara open my notes", self.rx), (True, "open my notes"))
        self.assertEqual(split_wake("I told Claire yesterday", self.rx), (False, ""))
        self.assertEqual(split_wake("Clarence is here", self.rx), (False, ""))

    def test_handsfree_loop(self):
        heard = iter(["people talking", "Hey Claire what's the time", "Claire"])
        stop = threading.Event()

        class FakeEars:
            label = "fake"
            def record(self, ev, **kw):
                return "audio"
            def transcribe(self, a):
                try:
                    return next(heard)
                except StopIteration:
                    stop.set(); return ""
            def listen(self, ev, **kw):
                return "open my notes"
        vk = VoiceKit(vcfg(), "/")
        vk._ears = FakeEars()
        cmds, notes = [], []
        vk.handsfree(cmds.append, notes.append, stop)
        self.assertEqual(cmds, ["what's the time", "open my notes"])
        self.assertEqual(notes, ["ack"])


class Conversation(unittest.TestCase):
    def app(self, reply="It's quarter past three. Anything else?"):
        a = cli.App.__new__(cli.App)
        a.c = make(tempfile.mkdtemp(), FakeBrain(reply))
        a.vk = VoiceKit(a.c.cfg, "/")
        a.mouth = FakeMouth()
        a.vk._speaker = Speaker(a.mouth)
        a.user = "Carl"
        self.saved = {}
        self._old = cli.config.save_setting
        cli.config.save_setting = lambda k, v, *x: self.saved.__setitem__(k, v)
        return a

    def tearDown(self):
        cli.config.save_setting = self._old

    def test_spoken_question_is_spoken_back(self):
        a = self.app()
        a.handle("what time is it", spoken=True)
        a.vk.speaker.wait()
        self.assertEqual(a.mouth.said, ["It's quarter past three.", "Anything else?"])
        self.assertIn("SPEAKING to you", a.c.brain.calls[-1][0]["content"])
        self.assertIn("Found my voice", [r["title"] for r in a.c.store.journal()])

    def test_typed_question_stays_quiet_in_auto(self):
        a = self.app()
        a.handle("what time is it")
        a.vk.speaker.wait()
        self.assertEqual(a.mouth.said, [])
        self.assertNotIn("SPEAKING to you", a.c.brain.calls[-1][0]["content"])

    def test_voice_commands(self):
        a = self.app()
        a.handle("mute", spoken=True)
        self.assertEqual((a.vk.mode, self.saved["voice.speak"]), ("off", "off"))
        a.handle("talk to me", spoken=True)
        self.assertEqual(a.vk.mode, "on")
        self.assertEqual(len(a.c.brain.calls), 0)                 # handled locally, no LLM call
        self.assertFalse(a.handle("okay stop listening", spoken=True))


class Settings(unittest.TestCase):
    def test_nested_voice_settings_merge(self):
        p = Path(tempfile.mkdtemp()) / "s.json"
        p.write_text(json.dumps({"voice": {"speak": "on"}, "data_dir": str(p.parent)}))
        cfg = config.load(p)
        self.assertEqual(cfg["voice"]["speak"], "on")
        self.assertEqual(cfg["voice"]["stt_model"], "base.en")
        config.save_setting("voice.mic", 3, p)
        self.assertEqual(json.loads(p.read_text())["voice"], {"speak": "on", "mic": 3})


if __name__ == "__main__":
    unittest.main()
