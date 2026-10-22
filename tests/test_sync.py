"""Her voice and her words stay together: nothing is clipped at the end, and each sentence appears as she says it."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claire import voice                                            # noqa: E402
from claire.voice import Player, Speaker                             # noqa: E402
from test_phase1 import FakeBrain                                    # noqa: E402
from test_phase3 import make_session                                 # noqa: E402

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "numpy arrives with setup_voice")
class NothingIsClipped(unittest.TestCase):
    def test_silence_is_added_so_the_last_word_finishes(self):
        got = {}
        fake = types.SimpleNamespace(play=lambda s, r: got.update(s=s, r=r), wait=lambda: None, stop=lambda: None)
        speech = np.ones(16000, dtype="float32") * 0.3
        with mock.patch.dict(sys.modules, {"sounddevice": fake}):
            Player().pcm(speech, 24000)
        s = got["s"]
        lead, tail = int(24000 * Player.LEAD), int(24000 * Player.TAIL)
        self.assertEqual(len(s), 16000 + lead + tail)
        self.assertTrue(np.all(s[:lead] == 0) and np.all(s[-tail:] == 0))
        self.assertTrue(np.all(s[lead:-tail] == speech))
        self.assertEqual(s.dtype, speech.dtype)
        self.assertGreaterEqual(Player.TAIL, 0.3)


class Pipelined:
    """Renders and plays instantly, but logs the order of things."""
    name, label = "fake", "Fake"

    def __init__(self, log):
        self.log = log

    def render(self, text):
        self.log.append("render " + text)
        return text

    def play(self, audio):
        self.log.append("play " + audio)

    def stop(self):
        pass


class SentenceTiming(unittest.TestCase):
    def test_each_sentence_is_announced_just_before_it_is_played(self):
        log = []
        sp = Speaker(Pipelined(log))
        sp.on_start = lambda t: log.append("show " + t)
        sp.say("One.", shown="One. ")
        sp.say("Two.", shown="Two. ")
        sp.wait()
        shows = [i for i, x in enumerate(log) if x.startswith("show")]
        plays = [i for i, x in enumerate(log) if x.startswith("play")]
        self.assertEqual([log[i] for i in shows], ["show One. ", "show Two. "])
        for sh, pl in zip(shows, plays):
            self.assertEqual(sh + 1, pl)                           # shown immediately before its own audio starts
        self.assertLess(plays[0], shows[1])                        # sentence two is NOT shown while one is playing

    def test_text_with_nothing_to_say_is_still_shown_in_order(self):
        log = []
        sp = Speaker(Pipelined(log))
        sp.on_start = lambda t: log.append("show " + t)
        sp.say("Hello.", shown="Hello. ")
        sp.say("```x = 1```", shown="```x = 1```")                 # spoken as "I've put the code on screen"
        sp.say("   ", shown="   ")
        sp.wait()
        self.assertEqual([x for x in log if x.startswith("show")], ["show Hello. ", "show ```x = 1```", "show    "])

    def test_stopping_cancels_the_text_that_was_not_said(self):
        log = []
        eng = Pipelined(log)
        sp = Speaker(eng)
        sp.on_start = lambda t: log.append("show " + t)
        sp.gen += 1                                                # as stop() does
        sp.q.put((sp.gen - 1, "old", "old "))
        sp.wait()
        self.assertEqual(log, [])


class WindowShowsWhatSheSays(unittest.TestCase):
    def run_turn(self, speak_mode):
        s, a = make_session("First sentence. Second sentence. Third one.")
        log = []
        a.vk.set_mode(speak_mode)
        a.mouth.say = lambda t: log.append("say " + t)
        real = s.hub.publish
        s.hub.publish = lambda kind, **kw: (log.append("show " + kw["text"]) if kind == "token" else None, real(kind, **kw))[1]
        s._answer("hello there", spoken=True)
        a.vk.speaker.wait()
        return log

    def test_when_speaking_each_sentence_appears_as_it_is_said(self):
        log = self.run_turn("on")
        shown = "".join(x[5:] for x in log if x.startswith("show"))
        self.assertEqual(shown.strip(), "First sentence. Second sentence. Third one.")
        order = [x.split(" ", 1)[1].strip() for x in log if x.split(" ", 1)[0] in ("say", "show")]
        for sentence in ("First sentence.", "Second sentence.", "Third one."):
            i = [j for j, x in enumerate(log) if x.startswith("show") and sentence in x][0]
            self.assertTrue(log[i + 1].startswith("say") and sentence in log[i + 1], log)   # text, then its voice

    def test_when_not_speaking_the_words_still_stream_live(self):
        log = self.run_turn("off")
        self.assertEqual("".join(x[5:] for x in log if x.startswith("show")), "First sentence. Second sentence. Third one.")
        self.assertFalse([x for x in log if x.startswith("say")])


if __name__ == "__main__":
    unittest.main()
