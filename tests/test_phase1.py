"""Phase 1 acceptance tests. Run: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claire import config                      # noqa: E402
from claire.brain import Brain, BrainOffline   # noqa: E402
from claire.core import Claire                 # noqa: E402
from claire.store import Store                 # noqa: E402


class FakeBrain:
    def __init__(self, reply="Hello Carl."):
        self.calls = []
        self.reply = reply

    def online(self):
        return True

    def chat(self, messages, stream=True, on_token=None, temperature=None, json_mode=False):
        self.calls.append(messages)
        if json_mode:
            return json.dumps({"summary": "Carl talked about his toolkit.",
                               "facts": [{"text": "Carl prefers short answers", "core": True},
                                         {"text": "Carl is building a PC assistant", "core": False}]})
        reply = self.reply
        if on_token:
            on_token(reply)
        return reply


def make(tmp, brain=None):
    cfg = json.loads(json.dumps(config.DEFAULTS))        # a private copy: tests must not change the real defaults
    cfg["data_dir"] = tmp
    return Claire(cfg, brain or FakeBrain(), Store(str(Path(tmp) / "t.db")))


class Phase1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 1.1 identity
    def test_identity_in_prompt(self):
        c = make(self.tmp)
        p = c.system_prompt("where did you come from")
        self.assertIn("SAFWAT Recruitment Toolkit", p)
        self.assertIn("Lagatuz Labs", p)
        self.assertIn("personal assistant", p)

    # 1.2 brain streaming + offline message
    def test_brain_streams_from_ollama(self):
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200); self.end_headers()
                for piece in ["Hel", "lo"]:
                    self.wfile.write((json.dumps({"message": {"content": piece}, "done": False}) + "\n").encode())
                self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())

            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode())

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        b = Brain(f"http://127.0.0.1:{srv.server_port}", "qwen2.5:7b")
        got = []
        self.assertEqual(b.chat([{"role": "user", "content": "hi"}], on_token=got.append), "Hello")
        self.assertEqual(got, ["Hel", "lo"])
        self.assertTrue(b.online())
        srv.shutdown()

    def test_brain_offline_is_friendly(self):
        b = Brain("http://127.0.0.1:9", "x", timeout=2)
        with self.assertRaises(BrainOffline) as e:
            b.chat([{"role": "user", "content": "hi"}])
        self.assertIn("Ollama", str(e.exception))
        self.assertFalse(b.online())

    # 1.4 memory
    def test_memory_save_search_dedupe_forget(self):
        s = Store(str(Path(self.tmp) / "m.db"))
        i = s.remember("Carl's favourite coffee is Spanish latte")
        self.assertIsNotNone(i)
        self.assertIsNone(s.remember("carl's favourite coffee is spanish latte."))
        self.assertEqual(len(s.search("what coffee do I like?")), 1)
        self.assertEqual(s.forget(str(i)), ["Carl's favourite coffee is Spanish latte."])
        self.assertEqual(s.search("coffee"), [])

    def test_relevant_memory_reaches_prompt(self):
        c = make(self.tmp)
        c.store.remember("Carl's sister is called Anna")
        c.store.remember("Carl lives in Riyadh", "core")
        p = c.system_prompt("when is my sister's birthday?")
        self.assertIn("Anna", p)
        self.assertIn("Riyadh", p)                     # core facts always present
        self.assertNotIn("Anna", c.system_prompt("what's the weather"))

    # 1.5 automatic memory
    def test_reflect_learns_facts(self):
        c = make(self.tmp)
        c.reply("I like short answers and I'm building you for my PC")
        summary, facts = c.reflect()
        self.assertEqual(summary, "Carl talked about his toolkit.")
        self.assertEqual(len(facts), 2)
        self.assertEqual(c.store.core_memories()[0]["text"], "Carl prefers short answers.")
        _, again = c.reflect()
        self.assertEqual(again, [])                    # duplicates skipped

    # 1.6 journal
    def test_journal_first_entries(self):
        c = make(self.tmp)
        titles = [r["title"] for r in c.store.journal()]
        self.assertTrue(titles[0].startswith("Born as the logic core"))
        self.assertEqual(titles[1], "Became Carl's personal assistant")
        make(self.tmp)                                 # restart: not duplicated
        self.assertEqual(len(c.store.journal()), 2)

    # 1.7 conversations persist & resume
    def test_restart_remembers_last_chat(self):
        c = make(self.tmp)
        c.reply("hello")                               # window closed without /quit
        c2 = make(self.tmp)
        rec = c2.recover()
        self.assertEqual(len(rec), 1)
        self.assertIn("Carl talked about his toolkit", c2.system_prompt("hi"))

    def test_history_is_sent_to_brain(self):
        b = FakeBrain()
        c = make(self.tmp, b)
        c.reply("first")
        c.reply("second")
        roles = [m["role"] for m in b.calls[-1]]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "user"][:len(roles)])
        self.assertEqual(b.calls[-1][-1]["content"], "second")


if __name__ == "__main__":
    unittest.main()
