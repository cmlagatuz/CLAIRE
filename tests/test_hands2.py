"""Phase 4.5 · Task Manager awareness, RAM watch and careful self-editing — fake PC, fake clock, temporary mini-repo."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claire import config                                           # noqa: E402
from claire.hands import procs, selfedit                             # noqa: E402
from claire.hands.files import Refused                               # noqa: E402
from claire.hands.selfedit import SelfEdit                           # noqa: E402
from claire.hands.tools import Hands                                 # noqa: E402
from claire.hands.watch import RamWatch                              # noqa: E402
from test_phase4 import FakePC                                       # noqa: E402


def mini_repo():
    root = Path(tempfile.mkdtemp()).resolve()
    for d in ("claire", "claire/hands", "tests", "data"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "claire" / "__init__.py").write_text("")
    (root / "claire" / "greet.py").write_text("def hi():\n    return 'hello'\n")
    (root / "claire" / "hands" / "tools.py").write_text("SAFE = True\n")
    (root / "claire" / "web.py").write_text("x = 1\n")
    (root / "settings.json").write_text("{}")
    (root / "start.bat").write_text("echo")
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "test_greet.py").write_text(
        "import unittest\nfrom claire import greet\nclass T(unittest.TestCase):\n"
        "    def test_hi(self):\n        self.assertIn('hello', greet.hi())\n")
    return root


def hands_for(root, runner):
    cfg = json.loads(json.dumps(config.DEFAULTS))
    cfg["data_dir"] = tempfile.mkdtemp()
    pc = FakePC()
    return Hands(cfg, pc, root=root, runner=runner), pc


class Procs(unittest.TestCase):
    def test_grouping_and_wording(self):
        g = procs.group(FakePC().procs)
        self.assertEqual(procs.key(g[0]["name"]), "ollama")
        chrome = [e for e in g if procs.key(e["name"]) == "chrome"][0]
        self.assertEqual((chrome["count"], chrome["mb"]), (8, 3200.0))
        text = procs.describe(g, 3)
        self.assertIn("Chrome 3.1 GB (8 processes)", text)
        self.assertIn("(system, off limits)", text)

    def test_never_suggests_system_or_herself(self):
        for n in ("svchost.exe", "System", "explorer.exe", "lsass.exe", "python.exe", "pythonw.exe", "ollama.exe",
                  "ollama app.exe", "powershell.exe", "cmd.exe", "MsMpEng.exe", "csrss.exe", "winlogon.exe"):
            self.assertTrue(procs.protected(n), n)
        self.assertEqual(procs.key(procs.closable(procs.group(FakePC().procs))["name"]), "chrome")
        self.assertIsNone(procs.closable([{"name": "svchost.exe", "count": 1, "mb": 5000.0, "protected": True}]))

    def test_this_machine_can_be_read(self):
        rows = procs.read()
        self.assertTrue(rows)
        self.assertTrue(all(set(r) == {"name", "pid", "mb"} for r in rows))


class Closing(unittest.TestCase):
    def setUp(self):
        self.h, self.pc = hands_for(mini_repo(), lambda t: (True, "ok"))

    def test_top_processes_is_free(self):
        r = self.h.call("top_processes", {"count": 2})
        self.assertEqual(r["status"], "done")
        self.assertIn("Ollama", r["text"])
        self.assertEqual(self.pc.did, [])

    def test_closing_asks_and_is_graceful(self):
        r = self.h.call("close_program", {"name": "CHROME"})
        self.assertEqual(r["status"], "pending")
        self.assertIn("Close Chrome (8 processes, 3.1 GB)", self.h.pending()[0]["what"])
        self.assertEqual(self.pc.did, [])
        self.assertEqual(self.h.answer("yes"), "I asked Chrome to close.")
        self.assertEqual(self.pc.did, [("close", "chrome.exe")])

    def test_protected_missing_and_sneaky_names_are_refused(self):
        for n in ("svchost", "explorer.exe", "python", "ollama", "nothing-running", "chrome.exe & del *", "..\\x",
                  "chrome;rm", "", "-9"):
            self.assertEqual(self.h.call("close_program", {"name": n})["status"], "error", n)
        self.assertEqual((self.pc.did, self.h.pending()), ([], []))

    def test_always_never_applies_to_closing_or_self_editing(self):
        saved = []
        self.h.persist = lambda k, v: saved.append(v)
        self.h.call("close_program", {"name": "chrome"})
        self.assertIn("always ask", self.h.answer("always"))
        self.assertEqual(self.h.call("close_program", {"name": "chrome"})["status"], "pending")
        self.assertEqual(saved, [])
        h2, _ = hands_for(mini_repo(), lambda t: (True, "ok"))
        h2.always = set(config.DEFAULTS["tools"]["always"])
        for n in ("apply_change", "undo_change", "close_program"):
            self.assertIn(n, __import__("claire.hands.tools", fromlist=["x"]).NO_ALWAYS)
        h3, _ = hands_for(mini_repo(), lambda t: (True, "ok"))
        h3.t["always"] = ["apply_change", "close_program", "open_app"]
        self.assertEqual(Hands(dict(h3.cfg), FakePC(), root=h3.selfedit.root).always, {"open_app"})


class Watching(unittest.TestCase):
    def setUp(self):
        self.h, self.pc = hands_for(mini_repo(), lambda t: (True, "ok"))
        self.said, self.now, self.pct = [], [1000.0], [90]
        self.w = RamWatch(self.h, self.said.append, warn_at=85, quiet_for=900, clock=lambda: self.now[0],
                          reader=lambda: {"mem_total": 100, "mem_free": 100 - self.pct[0]})

    def test_quiet_when_memory_is_fine(self):
        self.pct[0] = 60
        self.assertIsNone(self.w.check())
        self.assertEqual(self.said, [])

    def test_warns_names_the_culprits_and_asks_before_closing(self):
        text = self.w.check()
        self.assertIn("Memory is at 90%", text)
        self.assertIn("Want me to close Chrome?", text)
        self.assertEqual(self.said, [text])
        self.assertEqual(self.h.pending()[0]["tool"], "close_program")
        self.assertEqual(self.pc.did, [])                       # she only asked

    def test_does_not_nag(self):
        self.w.check()
        self.now[0] += 60
        self.assertIsNone(self.w.check())
        self.now[0] += 900
        self.assertIsNotNone(self.w.check())
        self.assertEqual(len(self.said), 2)
        self.assertEqual(len(self.h.pending()), 1)              # the same question is not asked twice

    def test_no_hands_no_question(self):
        self.h.t["enabled"] = False
        self.assertIn("Memory is at", self.w.check())
        self.assertEqual(self.h.pending(), [])


class EditRules(unittest.TestCase):
    def setUp(self):
        self.root = mini_repo()
        self.se = SelfEdit(self.root, tempfile.mkdtemp(), runner=lambda t: (True, "ok"))

    def test_good_paths(self):
        self.assertEqual(self.se.rel("claire/greet.py")[0], "claire/greet.py")
        self.assertEqual(self.se.rel("claire\\greet.py")[0], "claire/greet.py")
        self.assertEqual(self.se.rel("README.md")[0], "README.md")
        self.assertEqual(self.se.rel("tests/test_new.py")[0], "tests/test_new.py")

    def test_bad_paths(self):
        for p in ("claire/hands/tools.py", "claire/hands/new_tool.py", "claire/web.py", "claire/cli.py",
                  "claire/config.py", "tests/test_phase4.py", "tests/test_hands2.py", "settings.json", "start.bat",
                  "data/claire.db", ".gitignore", "C:/Windows/x.py", "/etc/passwd", "../x.py", "claire/../../x.py",
                  "claire//x.py", "claire/x.exe", "claire/x.bat", "claire/x", "setup_claire.bat", "identity.txt", "", None):
            with self.assertRaises(Refused, msg=repr(p)):
                self.se.rel(p)

    def test_protected_files_can_still_be_read(self):
        self.assertIn("SAFE", self.se.read("claire/hands/tools.py"))
        with self.assertRaises(Refused):
            self.se.read("settings.json")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_out_of_the_folder_is_refused(self):
        outside = Path(tempfile.mkdtemp()) / "evil.py"
        outside.write_text("x")
        (self.root / "claire" / "link.py").symlink_to(outside)
        with self.assertRaises(Refused):
            self.se.rel("claire/link.py")


class EditFlow(unittest.TestCase):
    def setUp(self):
        self.root = mini_repo()
        self.se = SelfEdit(self.root, tempfile.mkdtemp(), runner=lambda t: (True, "ok"))
        self.f = self.root / "claire" / "greet.py"

    def test_proposing_changes_nothing(self):
        before = self.f.read_text()
        p = self.se.propose("claire/greet.py", "'hello'", "'hello Carl'", "friendlier")
        self.assertEqual((p["status"], p["plus"], p["minus"], p["tests_ok"]), ("ready", 1, 1, True))
        self.assertIn("+    return 'hello Carl'", p["diff"])
        self.assertEqual(self.f.read_text(), before)

    def test_apply_backs_up_and_undo_restores(self):
        before = self.f.read_text()
        p = self.se.propose("claire/greet.py", "'hello'", "'hello Carl'", "r")
        self.se.apply(p["id"])
        self.assertIn("hello Carl", self.f.read_text())
        self.assertEqual(self.se.load(p["id"])["status"], "applied")
        self.se.undo()
        self.assertEqual(self.f.read_text(), before)
        with self.assertRaises(Refused):
            self.se.undo()

    def test_new_file_and_its_undo(self):
        p = self.se.propose("claire/extra.py", "", "X = 1\n", "new")
        self.se.apply(p["id"])
        self.assertTrue((self.root / "claire" / "extra.py").exists())
        self.se.undo(p["id"])
        self.assertFalse((self.root / "claire" / "extra.py").exists())

    def test_refuses_bad_proposals(self):
        for old, new in (("'nope'", "x"), ("", "x"), ("'hello'", "'hello'"), ("return", "retur n(")):
            with self.assertRaises(Refused, msg=old + new):
                self.se.propose("claire/greet.py", old, new, "r")
        with self.assertRaises(Refused):
            self.se.propose("claire/greet.py", "e", "E", "r")           # 'e' appears many times
        with self.assertRaises(Refused):
            self.se.propose("claire/hands/tools.py", "True", "False", "weaken myself")
        with self.assertRaises(Refused):
            self.se.propose("claire/greet.py", "", "X = 1\n", "already exists")

    def test_failing_tests_block_the_change(self):
        se = SelfEdit(self.root, tempfile.mkdtemp(), runner=lambda t: (False, "FAILED (failures=1)"))
        p = se.propose("claire/greet.py", "'hello'", "'bye'", "breaks it")
        self.assertEqual((p["status"], p["tests_ok"]), ("failed", False))
        with self.assertRaises(Refused):
            se.apply(p["id"])
        self.assertIn("hello", self.f.read_text())

    def test_stale_proposals_are_not_applied_over_newer_work(self):
        p = self.se.propose("claire/greet.py", "'hello'", "'hi'", "r")
        self.f.write_text("def hi():\n    return 'edited by Carl'\n")
        with self.assertRaises(Refused):
            self.se.apply(p["id"])
        self.assertIn("edited by Carl", self.f.read_text())

    def test_undo_will_not_overwrite_later_edits(self):
        p = self.se.propose("claire/greet.py", "'hello'", "'hi'", "r")
        self.se.apply(p["id"])
        self.f.write_text("Carl rewrote it\n")
        with self.assertRaises(Refused):
            self.se.undo(p["id"])
        self.assertEqual(self.f.read_text(), "Carl rewrote it\n")

    def test_a_proposal_cannot_be_retargeted_into_a_protected_file(self):
        p = self.se.propose("claire/greet.py", "'hello'", "'hi'", "r")
        path = self.se.dir / f"{p['id']}.json"
        data = json.loads(path.read_text())
        data["path"] = "claire/hands/tools.py"
        path.write_text(json.dumps(data))
        with self.assertRaises(Refused):
            self.se.apply(p["id"])


class RealSandbox(unittest.TestCase):
    """Uses the real test runner on a copy: a good change passes, a breaking one is caught, the real files stay put."""
    def test_good_and_bad(self):
        root = mini_repo()
        se = SelfEdit(root, tempfile.mkdtemp())
        good = se.propose("claire/greet.py", "return 'hello'", "return 'hello there'", "ok")
        self.assertTrue(good["tests_ok"], good["tests"])
        bad = se.propose("claire/greet.py", "return 'hello'", "return 'goodbye'", "breaks test_hi")
        self.assertFalse(bad["tests_ok"])
        self.assertEqual((root / "claire" / "greet.py").read_text(), "def hi():\n    return 'hello'\n")
        self.assertFalse(list(root.rglob("claire-test-*")))


class ThroughTheTools(unittest.TestCase):
    def setUp(self):
        self.root = mini_repo()
        self.h, self.pc = hands_for(self.root, lambda t: (True, "ok"))

    def test_the_whole_conversation(self):
        r = self.h.call("read_own_file", {"path": "claire/greet.py"})
        self.assertIn("hello", r["text"])
        r = self.h.call("propose_change", {"path": "claire/greet.py", "old": "'hello'", "new": "'hello Carl'", "reason": "warmer"})
        self.assertEqual(r["status"], "done")
        self.assertIn("Change #1", r["text"])
        self.assertIn("hello'", (self.root / "claire" / "greet.py").read_text())      # not applied yet
        q = self.h.call("apply_change", {"id": 1})
        self.assertEqual(q["status"], "pending")
        self.assertIn("Change my own code", self.h.pending()[0]["what"])
        self.assertIn("claire/greet.py", self.h.pending()[0]["what"])
        self.assertIn("Applied change #1", self.h.answer("yes"))
        self.assertIn("hello Carl", (self.root / "claire" / "greet.py").read_text())
        self.h.call("undo_change", {})
        self.assertIn("Undid change #1", self.h.answer("yes"))
        self.assertIn("'hello'", (self.root / "claire" / "greet.py").read_text())
        self.assertEqual([e["event"] for e in self.h.history()][:2], ["done", "approved"])

    def test_she_cannot_apply_what_does_not_exist_or_failed(self):
        self.assertEqual(self.h.call("apply_change", {"id": 99})["status"], "error")
        self.assertEqual(self.h.call("apply_change", {"id": "x"})["status"], "error")
        h, _ = hands_for(self.root, lambda t: (False, "FAILED"))
        h.call("propose_change", {"path": "claire/greet.py", "old": "'hello'", "new": "'x'", "reason": "r"})
        self.assertEqual(h.call("apply_change", {"id": 1})["status"], "error")

    def test_protected_files_are_refused_through_the_tool_too(self):
        r = self.h.call("propose_change", {"path": "claire/hands/tools.py", "old": "True", "new": "False", "reason": "x"})
        self.assertEqual(r["status"], "error")
        self.assertIn("safety rules", r["text"])
        self.assertEqual((self.root / "claire" / "hands" / "tools.py").read_text(), "SAFE = True\n")


if __name__ == "__main__":
    unittest.main()


class SeeBeforeYouApprove(unittest.TestCase):
    def test_the_question_carries_the_diff(self):
        root = mini_repo()
        h, _ = hands_for(root, lambda t: (True, "ok"))
        h.call("propose_change", {"path": "claire/greet.py", "old": "'hello'", "new": "'hello Carl'", "reason": "warmer"})
        h.call("apply_change", {"id": 1})
        item = h.pending()[0]
        self.assertIn("+    return 'hello Carl'", item["detail"])
        self.assertIn("-    return 'hello'", item["detail"])
        html = (Path(__file__).resolve().parent.parent / "claire" / "ui" / "orb.html").read_text(encoding="utf-8")
        self.assertIn("asking.detail", html)
        self.assertNotIn("innerHTML", html)
