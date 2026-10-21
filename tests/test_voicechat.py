"""Choosing her voice by talking, and the window's Voice tab — no microphone, speakers or models needed."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claire import cli, config, web                                   # noqa: E402
from claire.voice import KOKORO_VOICES, Speaker, VoiceKit              # noqa: E402
from claire.voicechat import VoiceChooser, VoiceControl, friendly, join_names   # noqa: E402
try:
    from tests.test_phase1 import FakeBrain, make                      # noqa: E402
    from tests.test_phase2 import FakeMouth                            # noqa: E402
    from tests.test_phase3 import HttpCase, wait_for                   # noqa: E402
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_phase1 import FakeBrain, make                            # noqa: E402
    from test_phase2 import FakeMouth                                  # noqa: E402
    from test_phase3 import HttpCase, wait_for                         # noqa: E402


class FakeKokoro:
    name, label = "kokoro", "Fake Kokoro"

    def __init__(self):
        self.spec, self.speed, self.said, self.stopped = "af_heart", 1.0, [], 0

    def set_voice(self, spec, speed=None):
        if spec not in KOKORO_VOICES and "+" not in spec:
            raise ValueError(spec)
        self.spec = spec
        if speed is not None:
            self.speed = speed

    def say(self, text):
        self.said.append((self.spec, text))

    def stop(self):
        self.stopped += 1


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self._old = config.save_setting
        config.save_setting = lambda k, v, *a: self.saved.append((k, v))     # never touch the real settings.json
        self.eng = FakeKokoro()
        cfg = json.loads(json.dumps(config.DEFAULTS))
        self.vk = VoiceKit(cfg, "/")
        self.vk._speaker = Speaker(self.eng)
        self.lines, self.milestones = [], []
        self.vc = VoiceChooser(self.vk, self.say, "Carl", lambda t, d="": self.milestones.append(t))

    def tearDown(self):
        config.save_setting = self._old

    def say(self, text, speak=True):
        self.lines.append(text)
        if speak and self.vk.mode != "off" and self.vk.speaker:
            self.vk.speaker.say(text)

    def talk(self, text):
        handled = self.vc.handle(text)
        self.vk.speaker.wait()
        return handled


class Understanding(unittest.TestCase):
    def test_asks_about_her_voice(self):
        for t in ("change your voice", "Can you change your voice please?", "what voices do you have",
                  "I want a different voice", "list your voices", "which voice are you using", "pick another voice",
                  "switch voices", "Claire, show me the voices"):
            self.assertTrue(VoiceChooser._wants_voices(" ".join(__import__("re").findall(r"[a-z0-9']+", t.lower()))), t)

    def test_leaves_everything_else_alone(self):
        for t in ("what's the weather", "I like your voice", "turn voice on", "show me the voice commands",
                  "send a voice message to Sam", "what time is it", "change the subject"):
            self.assertFalse(VoiceChooser._wants_voices(" ".join(__import__("re").findall(r"[a-z0-9']+", t.lower()))), t)

    def test_names(self):
        self.assertEqual(friendly("af_heart"), "Heart")
        self.assertEqual(friendly("bf_emma"), "Emma")
        self.assertEqual(friendly("en-US-AvaMultilingualNeural"), "Ava")
        self.assertEqual(friendly("en-GB-SoniaNeural"), "Sonia")
        self.assertEqual(join_names(["A", "B", "C"]), "A, B and C")
        self.assertEqual(join_names(["A"]), "A")


class Dialogue(Base):
    def test_lists_her_voices_by_group_and_waits(self):
        self.assertTrue(self.talk("change your voice"))
        menu = self.lines[0]
        self.assertIn("10 voices", menu)
        self.assertIn("American: Heart, Bella, Nicole, Aoede, Kore and Sarah", menu)
        self.assertIn("British: Emma, Isabella, Alice and Lily", menu)
        self.assertTrue(self.vc.pending)
        self.assertEqual(self.eng.said[0][0], "af_heart")              # the list is read in her current voice
        self.assertEqual(self.saved, [])

    def test_try_then_keep(self):
        self.talk("change your voice")
        self.assertTrue(self.talk("bella"))
        self.assertEqual(self.eng.spec, "af_bella")
        self.assertEqual(self.eng.said[-1][0], "af_bella")             # the sample is spoken in the new voice
        self.assertIn("sound like this", self.lines[-1])
        self.assertEqual(self.saved, [])                               # not kept yet
        self.assertTrue(self.vc.pending)
        self.assertTrue(self.talk("yes keep it"))
        self.assertEqual(self.saved, [("voice.kokoro_voice", "af_bella")])
        self.assertFalse(self.vc.pending)
        self.assertIn("Bella", self.lines[-1])
        self.assertEqual(self.milestones, ["Chose my voice: af_bella"])
        self.assertEqual(self.vk.v["kokoro_voice"], "af_bella")

    def test_try_several_then_never_mind_goes_back(self):
        self.talk("what voices do you have")
        self.talk("try emma")
        self.talk("the first one")                                      # = Heart again
        self.talk("how about sarah")
        self.assertEqual(self.eng.spec, "af_sarah")
        self.talk("never mind")
        self.assertEqual(self.eng.spec, "af_heart")
        self.assertEqual(self.saved, [])
        self.assertFalse(self.vc.pending)

    def test_direct_choice_keeps_immediately(self):
        self.talk("change your voice")
        self.talk("use the second one")
        self.assertEqual(self.saved, [("voice.kokoro_voice", "af_bella")])
        self.assertFalse(self.vc.pending)
        self.talk("change your voice")
        self.talk("I'll take Emma")
        self.assertEqual(self.eng.spec, "bf_emma")

    def test_group_word_narrows_the_list(self):
        self.talk("change your voice")
        self.talk("the british ones")
        self.assertIn("Emma, Isabella, Alice and Lily", self.lines[-1])
        self.assertTrue(self.vc.pending)

    def test_faster_and_slower(self):
        self.talk("change your voice")
        self.talk("faster")
        self.assertAlmostEqual(self.eng.speed, 1.1)
        self.talk("slower")
        self.talk("slower")
        self.assertAlmostEqual(self.eng.speed, 0.9)
        self.assertIn(("voice.speed", 0.9), self.saved)
        self.assertTrue(self.vc.pending)

    def test_speed_works_without_the_menu_too(self):
        self.assertTrue(self.talk("could you speak a bit slower"))
        self.assertAlmostEqual(self.eng.speed, 0.9)
        self.assertFalse(self.vc.pending)

    def test_speed_has_limits(self):
        for _ in range(12):
            self.talk("speak faster")
        self.assertEqual(self.eng.speed, 1.4)

    def test_something_else_ends_it_and_restores(self):
        self.talk("change your voice")
        self.talk("kore")
        self.assertEqual(self.eng.spec, "af_kore")
        self.assertFalse(self.talk("what time is it"))                 # not for her voice → the normal chat takes it
        self.assertEqual(self.eng.spec, "af_heart")
        self.assertFalse(self.vc.pending)

    def test_keep_before_hearing_anything_asks_which(self):
        self.talk("change your voice")
        self.talk("yes")
        self.assertIn("Which one", self.lines[-1])
        self.assertTrue(self.vc.pending)

    def test_normal_questions_are_never_taken(self):
        for t in ("what's the weather like", "remind me to call Sam", "good morning"):
            self.assertFalse(self.talk(t), t)

    def test_voice_muted_means_no_dialogue(self):
        self.vk.v["speak"] = "off"
        self.assertTrue(self.talk("change your voice"))
        self.assertIn("muted", self.lines[-1])
        self.assertFalse(self.vc.pending)
        self.assertEqual(self.eng.said, [])

    def test_blended_voice_comes_back_after_never_mind(self):
        self.eng.spec = "af_heart:0.7+bf_emma:0.3"
        self.talk("change your voice")
        self.talk("lily")
        self.talk("cancel")
        self.assertEqual(self.eng.spec, "af_heart:0.7+bf_emma:0.3")


class OneVoiceOnly(unittest.TestCase):
    def test_basic_engine_explains_instead_of_failing(self):
        cfg = json.loads(json.dumps(config.DEFAULTS))
        vk = VoiceKit(cfg, "/")
        vk._speaker = Speaker(FakeMouth())
        lines = []
        vc = VoiceChooser(vk, lambda t, s=True: lines.append(t), "Carl")
        self.assertTrue(vc.handle("change your voice"))
        self.assertIn("setup_voice", lines[0])
        self.assertFalse(vc.pending)
        self.assertTrue(vc.handle("speak faster"))
        self.assertIn("setup_voice", lines[1])


class HandsFreeFollowUp(Base):
    def test_she_listens_again_without_the_wake_word_while_waiting_for_your_answer(self):
        heard = iter(["Hey Claire change your voice"])
        answers = iter(["bella", "keep it", ""])
        stop, cmds, notes = threading.Event(), [], []

        class Ears:
            label = "fake"

            def record(self, ev, **kw):
                return "audio"

            def transcribe(self, a):
                try:
                    return next(heard)
                except StopIteration:
                    stop.set()
                    return ""

            def listen(self, ev, **kw):
                return next(answers)
        self.vk._ears = Ears()

        def on_command(c):
            cmds.append(c)
            self.vc.handle(c)
        self.vk.handsfree(on_command, notes.append, stop, follow_up=lambda: self.vc.pending)
        self.assertEqual(cmds, ["change your voice", "bella", "keep it"])
        self.assertEqual(self.saved, [("voice.kokoro_voice", "af_bella")])
        self.assertEqual(notes, [])

    def test_silence_ends_the_follow_up(self):
        heard, stop, notes, cmds = iter(["Claire change your voice"]), threading.Event(), [], []

        class Ears:
            label = "fake"

            def record(self, ev, **kw):
                return "audio"

            def transcribe(self, a):
                try:
                    return next(heard)
                except StopIteration:
                    stop.set()
                    return ""

            def listen(self, ev, **kw):
                return ""
        self.vk._ears = Ears()
        self.vk.handsfree(lambda c: (cmds.append(c), self.vc.handle(c)), notes.append, stop,
                          follow_up=lambda: self.vc.pending)
        self.assertEqual(cmds, ["change your voice"])
        self.assertEqual(notes, ["end"])


def make_session():
    a = cli.App.__new__(cli.App)
    a.c = make(tempfile.mkdtemp(), FakeBrain("Hello."))
    a.c.cfg["voice"] = json.loads(json.dumps(a.c.cfg["voice"]))
    a.vk = VoiceKit(a.c.cfg, "/")
    a.eng = FakeKokoro()
    a.vk._speaker = Speaker(a.eng)
    a.user = "Carl"
    return web.WebSession(app=a), a


class WindowVoiceTab(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self._old = config.save_setting
        config.save_setting = lambda k, v, *a: self.saved.append((k, v))
        self.s, self.a = make_session()

    def tearDown(self):
        config.save_setting = self._old

    def test_listing(self):
        v = self.s.voices()
        self.assertEqual((v["kind"], v["current"], v["speed"]), ("kokoro", "af_heart", 1.0))
        self.assertEqual(len(v["items"]), 10)
        self.assertEqual(v["items"][0]["who"], "Heart")
        self.assertEqual(v["note"], "")

    def test_try_speaks_and_goes_back(self):
        self.assertTrue(self.s.voice_try("bf_emma"))
        self.assertTrue(wait_for(lambda: self.a.eng.said and self.a.eng.spec == "af_heart" and not self.s.turn_lock.locked()))
        self.assertEqual(self.a.eng.said[0][0], "bf_emma")
        self.assertEqual(self.saved, [])
        self.assertFalse(self.s.voice_try("nonsense"))

    def test_use_saves(self):
        self.assertTrue(self.s.voice_use("af_nicole"))
        self.assertEqual((self.a.eng.spec, self.saved), ("af_nicole", [("voice.kokoro_voice", "af_nicole")]))
        self.assertFalse(self.s.voice_use("nonsense"))

    def test_speed_is_clamped(self):
        self.assertEqual(self.s.voice_speed(5), 1.4)
        self.assertEqual(self.s.voice_speed(0.1), 0.7)
        self.assertEqual(self.s.voice_speed(1.05), 1.05)

    def test_voice_dialogue_works_in_the_window_too(self):
        q = self.s.hub.subscribe()
        self.s.turn("change your voice")
        got = []
        while not q.empty():
            got.append(q.get_nowait())
        texts = [d["text"] for k, d in got if k == "claire"]
        self.assertTrue(texts and "10 voices" in texts[0])
        self.assertTrue(self.s.chooser.pending)
        self.assertEqual(self.a.c.brain.calls, [])                     # it never went to the language model
        self.s.turn("kore")
        self.assertEqual(self.a.eng.spec, "af_kore")
        self.assertEqual(self.s._follow_up(), True)                    # hands-free keeps listening for the answer
        self.s.turn("keep it")
        self.assertFalse(self.s._follow_up())

    def test_basic_engine_gets_a_note(self):
        self.a.vk._speaker = Speaker(FakeMouth())
        v = self.s.voices()
        self.assertIsNone(v["kind"])
        self.assertEqual(v["items"], [])
        self.assertTrue(v["note"])
        self.assertIsNone(self.s.voice_speed(1.2))


class VoiceApi(HttpCase):
    __test__ = True

    @classmethod
    def make_session(cls):
        cls._saved = config.save_setting
        config.save_setting = lambda *a, **k: None
        s, cls.app = make_session()
        return s

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        config.save_setting = cls._saved

    def call(self, path, **body):
        code, data = self.post(path, body=json.dumps(body).encode())
        return code, json.loads(data)

    def test_needs_the_secret(self):
        for path in ("/api/voices", "/api/voice_use", "/api/voice_try", "/api/speed"):
            self.assertEqual(self.req("POST", path, b"{}", headers={"Content-Type": "application/json"})[0], 403)
            self.assertEqual(self.post(path, headers={"X-Claire-Token": "wrong"})[0], 403)

    def test_roundtrip(self):
        code, v = self.call("/api/voices")
        self.assertEqual((code, v["kind"]), (200, "kokoro"))
        self.assertEqual(self.call("/api/voice_use", name="bf_alice")[1], {"ok": True})
        self.assertEqual(self.call("/api/voices")[1]["current"], "bf_alice")
        self.assertEqual(self.call("/api/voice_use", name="x; drop table")[1], {"ok": False})
        self.assertEqual(self.call("/api/speed", value=1.2)[1], {"speed": 1.2})
        self.assertEqual(self.call("/api/speed", value="fast")[0], 400)
        self.assertEqual(self.call("/api/speed")[0], 400)


def _browser_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_browser_available(), "needs a headless browser (skipped on normal PCs)")
class PanelRace(unittest.TestCase):
    """Regression: opening Voice starts the memories list first; if that slower answer arrived last it was drawn
    with the wrong layout (rows of 'undefined') on top of the voices."""

    def test_slow_memories_answer_never_overwrites_the_voice_tab(self):
        from playwright.sync_api import sync_playwright
        saved, config.save_setting = config.save_setting, (lambda *a, **k: None)
        s, _ = make_session()
        for i in range(6):
            s.remember(f"Fact number {i}")
        srv = web.Server(s, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                pg = b.new_page()
                pg.route("**/api/memories", lambda route: (time.sleep(0.8), route.continue_()))
                pg.goto(srv.url)
                pg.click("#voiceBtn")
                pg.wait_for_selector("#list .item")
                time.sleep(1.6)                                  # long enough for the slow answer to arrive
                text = pg.inner_text("#list")
                b.close()
            self.assertNotIn("undefined", text)
            self.assertIn("Heart", text)
            self.assertNotIn("Fact number", text)
        finally:
            srv.stopping = True
            srv.shutdown()
            srv.server_close()
            config.save_setting = saved


if __name__ == "__main__":
    unittest.main()
