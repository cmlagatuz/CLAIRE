"""Phase 3 · Face acceptance tests — no browser, microphone or speakers needed."""
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claire import cli, tray, voice, web                          # noqa: E402
from claire.signals import envelope, mic_level, signals           # noqa: E402
from claire.voice import Speaker, VoiceKit                        # noqa: E402
try:
    from tests.test_phase1 import FakeBrain, make                  # noqa: E402
    from tests.test_phase2 import FakeMouth                        # noqa: E402
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_phase1 import FakeBrain, make                        # noqa: E402
    from test_phase2 import FakeMouth                              # noqa: E402

try:
    import numpy as np
except ImportError:
    np = None


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def make_session(reply="It's quarter past three. Anything else?"):
    a = cli.App.__new__(cli.App)
    a.c = make(tempfile.mkdtemp(), FakeBrain(reply))
    a.c.cfg["voice"] = json.loads(json.dumps(a.c.cfg["voice"]))      # never share (or change) the defaults
    a.vk = VoiceKit(a.c.cfg, "/")
    a.mouth = FakeMouth()
    a.vk._speaker = Speaker(a.mouth)
    a.user = "Carl"
    return web.WebSession(app=a), a


@unittest.skipIf(np is None, "numpy arrives with setup_voice")
class Loudness(unittest.TestCase):
    def test_envelope_follows_the_voice(self):
        rate = 16000
        loud = np.sin(np.linspace(0, 440 * 6.28, rate // 2)) * 0.5
        quiet = loud * 0.05
        env = envelope(np.concatenate([loud, quiet, loud]), rate, hop=0.05)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in env))
        third = len(env) // 3
        self.assertGreater(min(env[:third - 1]), 0.7)
        self.assertLess(max(env[third + 1:2 * third - 1]), 0.2)

    def test_silence_and_short_audio_are_safe(self):
        self.assertEqual(envelope([], 16000), [0.0])
        self.assertTrue(all(v == 0 for v in envelope(np.zeros(16000), 16000)))

    def test_mic_level_range(self):
        self.assertEqual(mic_level(np.zeros(480)), 0.0)
        self.assertGreater(mic_level(np.ones(480) * 0.1), 0.9)
        self.assertLessEqual(mic_level(np.ones(480) * 5), 1.0)


class PlayerMeter(unittest.TestCase):
    def test_level_is_published_while_audio_plays_then_drops(self):
        p = voice.Player()
        p._meter([0.9, 0.9, 0.9, 0.9, 0.9], hop=0.02)
        self.assertTrue(wait_for(lambda: signals.level == 0.9))
        self.assertTrue(wait_for(lambda: signals.level == 0.0))

    def test_stop_silences_the_meter(self):
        p = voice.Player()
        p._meter([0.7] * 400, hop=0.02)
        self.assertTrue(wait_for(lambda: signals.level == 0.7))
        p.stop()
        self.assertEqual(signals.level, 0.0)

    def test_unknown_audio_means_no_level(self):
        voice.Player()._meter(None)
        self.assertIsNone(signals.level)
        signals.level = 0.0

    def test_mp3_has_no_envelope_wav_has(self):
        self.assertIsNone(voice.Player._wav_envelope("x.mp3"))
        if np is None:
            return
        import wave
        path = Path(tempfile.mkdtemp()) / "t.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes((np.sin(np.linspace(0, 900, 8000)) * 12000).astype("<i2").tobytes())
        env = voice.Player._wav_envelope(path)
        self.assertTrue(env and max(env) > 0.9)


class State(unittest.TestCase):
    def setUp(self):
        self.s, self.a = make_session()
        signals.activity, signals.level, signals.mic, signals.handsfree = "idle", None, 0.0, False
        self._save = cli.config.save_setting
        cli.config.save_setting = lambda *a, **k: None       # tests must never touch the real settings.json

    def tearDown(self):
        cli.config.save_setting = self._save

    def test_frame_states(self):
        self.assertEqual(self.s.frame()["s"], "idle")
        signals.activity = "thinking"
        self.assertEqual(self.s.frame()["s"], "thinking")
        signals.activity = "listening"; signals.mic = 0.4
        f = self.s.frame()
        self.assertEqual((f["s"], f["m"]), ("listening", 0.4))
        signals.activity = "responding"                     # typed answer streaming, no audio
        self.assertEqual(self.s.frame()["s"], "speaking")
        signals.activity = "idle"

    def test_speaking_reports_level_only_while_speaking(self):
        signals.level = 0.6
        self.assertIsNone(self.s.frame()["l"])
        self.a.vk._speaker.q.put((0, "x"))                 # something queued = she is speaking
        self.a.vk._speaker.q.task_done = lambda: None
        self.assertEqual(self.s.frame()["s"], "speaking")
        self.assertEqual(self.s.frame()["l"], 0.6)
        signals.level = None
        self.a.vk._speaker.q.get_nowait()

    def test_typed_message_round_trip(self):
        q = self.s.hub.subscribe()
        self.assertTrue(self.s.submit("what time is it"))
        got = []
        self.assertTrue(wait_for(lambda: (got.extend(self._drain(q)) or "claire_end" in [k for k, _ in got])))
        kinds = [k for k, _ in got]
        self.assertEqual(kinds[0], "user")
        self.assertIn("token", kinds)
        self.assertEqual("".join(d["text"] for k, d in got if k == "token"), "It's quarter past three. Anything else?")
        self.a.vk.speaker.wait()
        self.assertEqual(self.a.mouth.said, [])            # typed + auto = quiet
        self.assertEqual(signals.activity, "idle")

    def test_spoken_message_is_spoken_back(self):
        threading.Thread(target=self.s.turn, args=("what time is it", True)).start()
        self.assertTrue(wait_for(lambda: self.a.mouth.said))
        self.a.vk.speaker.wait()
        self.assertEqual(self.a.mouth.said, ["It's quarter past three.", "Anything else?"])

    def test_mute_command_and_mode_button(self):
        q = self.s.hub.subscribe()
        self.s.turn("mute")
        self.assertEqual(self.a.vk.mode, "off")
        self.assertTrue(any(k == "status" for k, _ in self._drain(q)))
        self.assertFalse(self.s.set_mode("loud"))

    def test_handsfree_tells_the_window_when_nothing_followed(self):
        heard = iter(["Claire"])
        stop = threading.Event()

        class Ears:
            label = "fake"
            def record(self, ev, **kw):
                return "audio"
            def transcribe(self, a):
                try:
                    return next(heard)
                except StopIteration:
                    stop.set(); return ""
            def listen(self, ev, **kw):
                return ""
        vk = VoiceKit(self.a.c.cfg, "/")
        vk._ears = Ears()
        notes = []
        vk.handsfree(lambda c: None, notes.append, stop)
        self.assertEqual(notes, ["ack", "end"])

    @staticmethod
    def _drain(q):
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out


class HttpCase(unittest.TestCase):
    """A real local server + helpers to call it. Subclasses set cls.session in make_session()."""
    __test__ = False

    @classmethod
    def make_session(cls):
        raise NotImplementedError

    @classmethod
    def setUpClass(cls):
        cls.session = cls.make_session()
        cls.srv = web.Server(cls.session, 0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.stopping = True
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.srv.port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def post(self, path="/api/say", body=b'{"text":"hi"}', **kw):
        h = {"Content-Type": "application/json", "X-Claire-Token": self.srv.token}
        h.update(kw.pop("headers", {}))
        return self.req("POST", path, body, headers=h, **kw)


class Safety(HttpCase):
    __test__ = True

    @classmethod
    def make_session(cls):
        cls.said = []
        return SimpleNamespace(
            hub=web.Hub(), submit=lambda t, spoken=False: cls.said.append(t) or True, talk=lambda: True,
            set_handsfree=lambda on: on, stop_speaking=lambda: None, set_mode=lambda m: True,
            frame=lambda: {"s": "idle", "l": None, "m": 0.0, "hf": False},
            status=lambda: {"model": "m", "mouth": "x", "speak": "auto"})

    def test_only_loopback_and_never_open_to_the_network(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_page_carries_the_secret_and_a_strict_policy(self):
        code, data = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(self.srv.token.encode(), data)
        self.assertNotIn(b"__TOKEN__", data)

    def test_page_has_all_four_behaviours(self):
        html = web.PAGE.read_text(encoding="utf-8")
        for word in ("idle", "listening", "thinking", "speaking"):
            self.assertIn(word, html)

    def test_good_post_works(self):
        code, data = self.post()
        self.assertEqual((code, json.loads(data)), (200, {"ok": True}))
        self.assertIn("hi", self.said)

    def test_refuses_strangers(self):
        self.assertEqual(self.post(headers={"X-Claire-Token": "wrong"})[0], 403)
        self.assertEqual(self.req("POST", "/api/say", b'{"text":"x"}', headers={"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.post(host="evil.example")[0], 403)                          # DNS rebinding
        self.assertEqual(self.post(headers={"Origin": "http://evil.example"})[0], 403)    # another website
        self.assertEqual(self.post(headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("GET", "/", host="evil.example")[0], 403)
        self.assertEqual(self.req("GET", "/events?t=nope")[0], 403)
        self.assertEqual(self.req("GET", "/etc/passwd")[0], 404)

    def test_bad_json_is_a_clean_400(self):
        self.assertEqual(self.post(body=b"{not json")[0], 400)

    def test_event_stream_sends_status_then_frames(self):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        c.request("GET", "/events?t=" + self.srv.token, headers={"Host": f"127.0.0.1:{self.srv.port}"})
        r = c.getresponse()
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream")
        text = b""
        end = time.time() + 3
        while time.time() < end and text.count(b"event: frame") < 2:
            text += r.fp.readline()
        c.close()
        self.assertIn(b"event: status", text)
        self.assertGreaterEqual(text.count(b"event: frame"), 2)


class Hotkeys(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(tray.parse_hotkey("ctrl+alt+c"), (0x2 | 0x1, ord("C")))
        self.assertEqual(tray.parse_hotkey("Ctrl + Shift + F9"), (0x2 | 0x4, 0x6F + 9))
        self.assertEqual(tray.parse_hotkey("win+space"), (0x8, 0x20))
        self.assertEqual(tray.parse_hotkey("alt+5"), (0x1, ord("5")))

    def test_refuses_keys_that_would_break_typing(self):
        for bad in ("c", "shift+c", "ctrl+", "ctrl+alt+nonsense", "hyper+c", ""):
            with self.assertRaises(ValueError, msg=bad):
                tray.parse_hotkey(bad)

    def test_not_windows_fails_softly(self):
        if sys.platform.startswith("win"):
            self.skipTest("this machine is Windows")
        hk = tray.Hotkey("ctrl+alt+c", lambda: None)
        with self.assertRaises(RuntimeError):
            hk.start()
        hk.stop()                                           # harmless when it never started

    def test_tray_is_optional(self):
        icon, why = tray.start_tray(lambda: None, lambda: None, lambda: None)
        if icon is None:
            self.assertIn("pystray", why)
        else:
            icon.stop()


class MemoryPanel(unittest.TestCase):
    def setUp(self):
        self.s, self.a = make_session()

    def test_remember_list_forget(self):
        self.assertTrue(self.s.remember("Carl likes tea"))
        self.assertTrue(self.s.remember("Carl is a night owl", core=True))
        self.assertIsNone(self.s.remember("Carl likes tea"))          # duplicates are ignored
        self.assertIsNone(self.s.remember("   "))
        rows = self.s.memories()
        self.assertEqual([r["kind"] for r in rows], ["fact", "core"])
        self.assertEqual(self.s.forget(rows[0]["id"]), ["Carl likes tea."])
        self.assertEqual(len(self.s.memories()), 1)
        self.assertEqual(self.s.forget("not a number"), [])           # the panel only forgets by id

    def test_journal_newest_first(self):
        n = len(self.s.journal())
        self.assertTrue(self.s.journal_add("A new thing"))
        self.assertFalse(self.s.journal_add("  "))
        j = self.s.journal()
        self.assertEqual((len(j), j[0]["title"]), (n + 1, "A new thing"))

    def test_long_text_is_capped(self):
        self.s.remember("x" * 5000)
        self.assertLessEqual(len(self.s.memories()[0]["text"]), 501)


class MemoryApi(HttpCase):
    """The same security rules cover the memory endpoints."""
    __test__ = True

    @classmethod
    def make_session(cls):
        s, cls.app = make_session()
        return s

    def call(self, path, **body):
        code, data = self.post(path, body=json.dumps(body).encode())
        return code, json.loads(data)

    def test_roundtrip_over_http(self):
        self.assertEqual(self.call("/api/remember", text="Carl lives in Riyadh", core=True)[0], 200)
        code, out = self.call("/api/memories")
        self.assertEqual(code, 200)
        item = [i for i in out["items"] if "Riyadh" in i["text"]][0]
        self.assertEqual(item["kind"], "core")
        self.assertEqual(self.call("/api/forget", id=item["id"])[1]["gone"], ["Carl lives in Riyadh."])
        self.call("/api/journal_add", text="http note")
        self.assertEqual(self.call("/api/journal")[1]["items"][0]["title"], "http note")

    def test_memory_is_not_readable_without_the_secret(self):
        for path in ("/api/memories", "/api/journal"):
            self.assertEqual(self.req("POST", path, b"{}", headers={"Content-Type": "application/json"})[0], 403)
            self.assertEqual(self.post(path, headers={"X-Claire-Token": "wrong"})[0], 403)
            self.assertEqual(self.req("GET", path)[0], 404)         # and never as a plain link

    def test_page_never_builds_html_from_memories(self):
        html = web.PAGE.read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", html)


if __name__ == "__main__":
    unittest.main()
