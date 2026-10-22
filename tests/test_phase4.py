"""Phase 4 · Hands — nothing here opens a window, presses a key or touches the real PC or real settings."""
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claire import config, web                                       # noqa: E402
from claire.brain import Brain, ToolsUnsupported                     # noqa: E402
from claire.hands import files, sysinfo                              # noqa: E402
from claire.hands.files import Refused                               # noqa: E402
from claire.hands.tools import Hands, check_url                      # noqa: E402
from test_phase1 import FakeBrain, make                              # noqa: E402
from test_phase3 import HttpCase, make_session                       # noqa: E402


class FakePC:
    """Records what she was asked to do instead of doing it."""
    def __init__(self, volume=True):
        self.did, self.volume = [], volume

    def can_change_volume(self):
        return self.volume

    def open_path(self, t):
        self.did.append(("open", t))

    def launch(self, c):
        self.did.append(("launch", c))

    def volume_taps(self, k, n):
        self.did.append(("volume", k, n))

    procs = [{"name": "chrome.exe", "pid": i, "mb": 400.0} for i in range(1, 9)] + [
        {"name": "Code.exe", "pid": 20, "mb": 900.0}, {"name": "svchost.exe", "pid": 30, "mb": 2000.0},
        {"name": "python.exe", "pid": 31, "mb": 700.0}, {"name": "ollama.exe", "pid": 32, "mb": 6000.0}]

    def list_processes(self):
        return list(self.procs)

    # ---- Phase 4.7 fakes
    ip = "192.168.1.10"
    arp = ("Interface: 192.168.1.10 --- 0x4\n  Internet Address      Physical Address      Type\n"
           "  192.168.1.1           aa-bb-cc-00-00-01     dynamic\n  192.168.1.20          aa-bb-cc-00-00-20     dynamic\n"
           "  192.168.1.255         ff-ff-ff-ff-ff-ff     static\n  224.0.0.22            01-00-5e-00-00-16     static\n")
    names = {"192.168.1.1": "router", "192.168.1.20": "galaxy"}
    adb_log, adb_out, shortcuts_hit = [], {}, []

    def local_ip(self):
        return self.ip

    def arp_table(self, sweep_net=None):
        self.swept = sweep_net
        return self.arp

    def device_name(self, ip):
        return self.names.get(ip, "")

    def adb(self, args, adb_path="adb"):
        self.adb_log.append(list(args))
        if self.adb_out is None:
            raise FileNotFoundError("adb")
        key = " ".join(args)
        for k, v in self.adb_out.items():
            if key.startswith(k):
                return v
        return 0, ""

    def http_get(self, url):
        self.shortcuts_hit.append(url)
        return 200

    def close_program(self, name):
        self.did.append(("close", name))


def setup_hands(tmp=None, **tools):
    tmp = tmp or tempfile.mkdtemp()
    cfg = json.loads(json.dumps(config.DEFAULTS))
    cfg["data_dir"] = tmp
    docs = Path(tmp) / "Documents"
    docs.mkdir(exist_ok=True)
    cfg["tools"]["folders"] = [str(docs)]
    cfg["tools"].update(tools)
    pc, now = FakePC(), [1000.0]
    h = Hands(cfg, pc, clock=lambda: now[0])
    h.now = now
    return h, pc, docs


class Sysinfo(unittest.TestCase):
    def test_reads_something_real(self):
        d = sysinfo.read()
        self.assertTrue(d)
        self.assertIn("Memory", sysinfo.describe(d, "memory"))

    def test_sentences(self):
        d = {"cpu": 12.4, "mem_total": 16 * 1024 ** 3, "mem_free": 4 * 1024 ** 3,
             "disks": [{"name": "D:", "total": 500 * 1024 ** 3, "free": 120 * 1024 ** 3}],
             "battery": {"percent": 80, "plugged": False}, "uptime": 90061}
        self.assertEqual(sysinfo.describe(d, "cpu"), "The processor is at 12%.")
        self.assertIn("12.0 GB of 16.0 GB in use (75%)", sysinfo.describe(d, "memory"))
        self.assertIn("D: has 120.0 GB free", sysinfo.describe(d, "disk"))
        self.assertIn("running on battery", sysinfo.describe(d, "battery"))
        self.assertIn("1 day 1 hour", sysinfo.describe(d, "uptime"))
        self.assertIn("desktop", sysinfo.describe({"cpu": 1}, "battery"))
        self.assertIn("couldn't", sysinfo.describe({}, "all"))


class FileSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.docs = self.tmp / "Documents"
        self.docs.mkdir()
        self.outside = self.tmp / "secret"
        self.outside.mkdir()
        (self.outside / "passwords.txt").write_text("x")
        (self.docs / "visa report.pdf").write_text("x")
        (self.docs / "setup.exe").write_text("x")
        self.allowed = [self.docs]

    def test_inside_is_fine(self):
        self.assertEqual(files.check_path(str(self.docs / "visa report.pdf"), self.allowed),
                         (self.docs / "visa report.pdf").resolve())

    def test_dotdot_escape_is_refused(self):
        with self.assertRaises(Refused):
            files.check_path(str(self.docs / ".." / "secret" / "passwords.txt"), self.allowed)

    def test_outside_and_sibling_with_same_prefix_are_refused(self):
        sib = self.tmp / "Documents-old"
        sib.mkdir()
        (sib / "a.txt").write_text("x")
        for p in (self.outside / "passwords.txt", sib / "a.txt", "/etc/passwd"):
            with self.assertRaises(Refused, msg=str(p)):
                files.check_path(str(p), self.allowed)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_out_of_the_folder_is_refused_and_not_found(self):
        (self.docs / "shortcut").symlink_to(self.outside)
        with self.assertRaises(Refused):
            files.check_path(str(self.docs / "shortcut" / "passwords.txt"), self.allowed)
        self.assertEqual(files.find("passwords", self.allowed), [])

    def test_network_and_device_paths_are_refused(self):
        for p in ("\\\\server\\share\\a.txt", "//server/share/a.txt", "a\0b", ""):
            with self.assertRaises(Refused, msg=repr(p)):
                files.check_path(p, self.allowed)

    def test_programs_are_never_opened(self):
        real = files.check_path(str(self.docs / "setup.exe"), self.allowed)
        with self.assertRaises(Refused):
            files.check_openable(real)
        for ext in (".bat", ".ps1", ".lnk", ".js", ".vbs", ".docm", ".py"):
            self.assertIn(ext, files.UNSAFE)

    def test_find_by_name_newest_first_and_skips_junk(self):
        (self.docs / "visa notes.txt").write_text("x")
        (self.docs / ".venv").mkdir()
        (self.docs / ".venv" / "visa hidden.txt").write_text("x")
        os.utime(self.docs / "visa report.pdf", (1, 1))
        found = files.find("the VISA file", self.allowed)
        self.assertEqual([Path(f).name for f in found], ["visa notes.txt", "visa report.pdf"])
        with self.assertRaises(Refused):
            files.find("   ", self.allowed)


class Urls(unittest.TestCase):
    def test_good(self):
        self.assertEqual(check_url("https://example.com/a?b=1"), "https://example.com/a?b=1")
        self.assertEqual(check_url("example.com"), "https://example.com")

    def test_bad(self):
        for u in ("file:///C:/Windows/system32/cmd.exe", "javascript:alert(1)", "ms-settings:", "ftp://a.com",
                  "https://google.com@evil.com", "https://user:pw@example.com", "http://exa mple.com",
                  "https://example.com/\nx", "", "notaurl", "cmd"):
            with self.assertRaises(Refused, msg=u):
                check_url(u)


class Approval(unittest.TestCase):
    def test_reading_is_free_and_logged(self):
        h, pc, _ = setup_hands()
        r = h.call("system_status", {"topic": "memory"})
        self.assertEqual(r["status"], "done")
        self.assertEqual(pc.did, [])
        self.assertEqual(h.history()[0]["event"], "done")

    def test_opening_waits_for_a_yes(self):
        h, pc, _ = setup_hands()
        r = h.call("open_app", {"name": "Notepad"})
        self.assertEqual(r["status"], "pending")
        self.assertEqual(pc.did, [])                          # nothing happened yet
        self.assertEqual(h.pending()[0]["what"], "Open Notepad")
        self.assertEqual(h.answer("yes"), "Opened notepad.")
        self.assertEqual(pc.did, [("launch", "notepad")])
        self.assertEqual(h.pending(), [])

    def test_no_and_unrelated_talk(self):
        h, pc, _ = setup_hands()
        h.call("open_website", {"url": "https://example.com"})
        self.assertIsNone(h.answer("what's the weather like"))
        self.assertEqual(len(h.pending()), 1)                 # still waiting
        self.assertIn("won't", h.answer("no thanks"))
        self.assertEqual(pc.did, [])
        self.assertEqual([e["event"] for e in h.history()][:2], ["denied", "asked"])

    def test_yes_variants(self):
        for word in ("yes", "Yes please", "go ahead", "okay.", "Sure!", "do it"):
            h, pc, _ = setup_hands()
            h.call("open_app", {"name": "paint"})
            self.assertTrue(h.answer(word), word)
            self.assertEqual(len(pc.did), 1, word)
        for word in ("yesterday I opened it", "okay so anyway", "what time is it"):
            h, pc, _ = setup_hands()
            h.call("open_app", {"name": "paint"})
            self.assertIsNone(h.answer(word), word)
            self.assertEqual(pc.did, [], word)

    def test_same_question_twice_is_one_question(self):
        h, _, _ = setup_hands()
        a = h.call("open_app", {"name": "notepad"})
        b = h.call("open_app", {"name": "notepad"})
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(h.pending()), 1)

    def test_unanswered_questions_expire(self):
        h, pc, _ = setup_hands()
        r = h.call("open_app", {"name": "notepad"})
        h.now[0] += 301
        self.assertEqual(h.pending(), [])
        self.assertEqual(h.approve(r["id"])["status"], "error")
        self.assertEqual(pc.did, [])

    def test_always_skips_future_questions_and_is_saved(self):
        h, pc, _ = setup_hands()
        saved = []
        h.persist = lambda k, v: saved.append((k, v))
        h.call("set_volume", {"action": "up"})
        self.assertIn("won't ask", h.answer("always") + " won't ask")
        self.assertEqual(saved, [("tools.always", ["set_volume"])])
        self.assertEqual(h.call("set_volume", {"action": "down"})["status"], "done")
        self.assertEqual(h.call("open_app", {"name": "notepad"})["status"], "pending")   # other tools still ask

    def test_always_for_unknown_tools_is_ignored(self):
        h, _, _ = setup_hands(always=["system_status", "rm_rf"])
        self.assertEqual(h.always, set())

    def test_apps_must_be_on_the_list(self):
        h, pc, _ = setup_hands()
        for n in ("cmd", "powershell", "C:\\Windows\\System32\\cmd.exe", ""):
            r = h.call("open_app", {"name": n})
            self.assertEqual(r["status"], "error", n)
        self.assertEqual(pc.did, [])

    def test_files_are_checked_before_asking_and_again_after(self):
        h, pc, docs = setup_hands()
        (docs / "a.txt").write_text("x")
        (docs / "bad.exe").write_text("x")
        self.assertEqual(h.call("open_file", {"path": str(docs / "bad.exe")})["status"], "error")
        self.assertEqual(h.call("open_file", {"path": "/etc/passwd"})["status"], "error")
        self.assertEqual(h.call("open_file", {"path": str(docs / "a.txt")})["status"], "pending")
        h.answer("yes")
        self.assertEqual(pc.did, [("open", str((docs / "a.txt").resolve()))])

    def test_there_is_no_way_to_delete_send_or_run(self):
        h, pc, _ = setup_hands()
        names = {s["function"]["name"] for s in h.specs()}
        self.assertEqual(names, {"system_status", "find_files", "open_file", "open_app", "open_website", "set_volume",
                                 "top_processes", "close_program", "read_own_file", "propose_change", "show_change",
                                 "apply_change", "undo_change", "network_map", "network_trust", "phone_status",
                                 "phone_connect", "phone_open_app", "run_shortcut", "search_documents",
                                 "index_documents", "health_status", "add_reminder", "list_reminders",
                                 "remove_reminder", "take_note", "list_notes", "screen_time"})
        for bad in ("delete_file", "run_command", "send_email", "shell", "install"):
            self.assertEqual(h.call(bad, {"command": "del *"})["status"], "error")
        self.assertEqual(pc.did, [])

    def test_volume_asks_and_taps(self):
        h, pc, _ = setup_hands(volume_step=10)
        h.call("set_volume", {"action": "up"})
        h.answer("yes")
        self.assertEqual(pc.did, [("volume", "up", 5)])
        self.assertEqual(h.call("set_volume", {"action": "loud"})["status"], "error")
        pc.volume = False
        self.assertEqual(h.call("set_volume", {"action": "up"})["status"], "error")

    def test_a_failing_pc_does_not_crash_her(self):
        h, pc, _ = setup_hands()
        pc.launch = mock.Mock(side_effect=FileNotFoundError("x"))
        h.call("open_app", {"name": "notepad"})
        self.assertIn("didn't work", h.answer("yes"))
        self.assertEqual(h.history()[0]["event"], "failed")

    def test_switched_off(self):
        h, _, _ = setup_hands(enabled=False)
        self.assertEqual(h.specs(), [])
        self.assertEqual(h.call("system_status", {})["status"], "error")

    def test_audit_log_is_json_lines(self):
        h, _, _ = setup_hands()
        h.call("open_app", {"name": "notepad"})
        h.answer("yes")
        rows = [json.loads(x) for x in h.log_path.read_text().splitlines()]
        self.assertEqual([r["event"] for r in rows], ["asked", "approved", "done"])
        self.assertTrue(all(r["tool"] == "open_app" and r["at"] for r in rows))


class ToolBrain(FakeBrain):
    """Asks for a tool on the first round, then answers using the result."""
    def __init__(self, calls, final="Done."):
        super().__init__(final)
        self.script, self.rounds = list(calls), []

    def chat_tools(self, messages, tools, on_token=None, temperature=None):
        self.rounds.append([m for m in messages])
        if self.script:
            return "", self.script.pop(0)
        if on_token:
            on_token(self.reply)
        return self.reply, []


class Thinking(unittest.TestCase):
    def claire(self, brain):
        c = make(tempfile.mkdtemp(), brain)
        h, pc, _ = setup_hands()
        c.hands = h
        return c, h, pc

    def test_she_asks_then_acts_after_yes(self):
        c, h, pc = self.claire(ToolBrain([[{"name": "open_app", "arguments": {"name": "notepad"}}]], "I've asked you."))
        self.assertEqual(c.reply("open notepad"), "I've asked you.")
        self.assertEqual(pc.did, [])
        self.assertIn("waiting for your yes", c.brain.rounds[-1][-1]["content"])
        h.answer("yes")
        self.assertEqual(pc.did, [("launch", "notepad")])

    def test_tool_result_is_given_back_to_the_model(self):
        c, h, _ = self.claire(ToolBrain([[{"name": "system_status", "arguments": {"topic": "memory"}}]], "Fine."))
        c.reply("how is my pc")
        last = c.brain.rounds[-1]
        self.assertEqual(last[-1]["role"], "tool")
        self.assertIn("Memory", last[-1]["content"])
        self.assertIn("You have hands", last[0]["content"])

    def test_endless_tool_loops_are_cut(self):
        c, _, _ = self.claire(ToolBrain([[{"name": "system_status", "arguments": {}}]] * 10))
        self.assertIn("couldn't finish", c.reply("check my pc memory loop"))
        self.assertEqual(len(c.brain.rounds), 4)

    def test_small_talk_is_a_plain_fast_chat_without_tools(self):
        c, h, _ = self.claire(ToolBrain([[{"name": "system_status", "arguments": {}}]], "I'm well, thanks."))
        for text in ("how are you today", "tell me a joke", "what do you think of jazz"):
            self.assertEqual(c.reply(text), "I'm well, thanks.")
        self.assertEqual(c.brain.rounds, [])                       # chat_tools was never called
        self.assertNotIn("You have hands", c.brain.calls[-1][0]["content"])

    def test_pc_requests_and_their_follow_ups_get_tools(self):
        c, h, _ = self.claire(ToolBrain([[{"name": "open_app", "arguments": {"name": "notepad"}}]], "Asked."))
        c.reply("please open notepad")
        self.assertEqual(len(c.brain.rounds), 2)
        self.assertTrue(c.hot)
        c.brain.script.append([{"name": "system_status", "arguments": {}}])
        c.reply("yes that one")                                   # no keyword, but it follows a tool turn
        self.assertEqual(len(c.brain.rounds), 4)
        c.reply("thanks")                                         # still a follow-up; no tool is called, so the window closes
        self.assertEqual(len(c.brain.rounds), 5)
        self.assertFalse(c.hot)
        c.reply("tell me a story")                                # back to the plain, fast chat
        self.assertEqual(len(c.brain.rounds), 5)

    def test_no_hands_means_plain_chat(self):
        c = make(tempfile.mkdtemp(), ToolBrain([]))
        self.assertEqual(c.reply("hi"), "Done.")
        self.assertNotIn("You have hands", c.brain.calls[-1][0]["content"])

    def test_model_without_tool_support_falls_back(self):
        class Plain(FakeBrain):
            def chat_tools(self, *a, **k):
                raise ToolsUnsupported("nope")
        c, _, _ = self.claire(Plain("Plain answer."))
        self.assertEqual(c.reply("open my files"), "Plain answer.")
        self.assertFalse(c.tools_ok)
        self.assertEqual(c.reply("open again"), "Plain answer.")


class FakeOllama(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.seen = body
        if FakeOllama.mode == "unsupported":
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"registry.ollama.ai/library/x does not support tools"}')
            return
        self.send_response(200)
        self.end_headers()
        for part in FakeOllama.parts:
            self.wfile.write((json.dumps(part) + "\n").encode())


class OllamaTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.brain = Brain(f"http://127.0.0.1:{cls.srv.server_address[1]}", "m", timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_streamed_tool_calls_are_collected(self):
        FakeOllama.mode = "ok"
        FakeOllama.parts = [
            {"message": {"content": "One sec. "}},
            {"message": {"content": "", "tool_calls": [{"function": {"name": "open_app", "arguments": {"name": "paint"}}}]}},
            {"message": {"tool_calls": [{"function": {"name": "set_volume", "arguments": "{\"action\": \"up\"}"}},
                                        {"function": {"arguments": {}}}]}},
            {"done": True}]
        got = []
        text, calls = self.brain.chat_tools([{"role": "user", "content": "hi"}], [{"type": "function"}], got.append)
        self.assertEqual((text, got), ("One sec. ", ["One sec. "]))
        self.assertEqual(calls, [{"name": "open_app", "arguments": {"name": "paint"}},
                                 {"name": "set_volume", "arguments": {"action": "up"}}])
        self.assertEqual(FakeOllama.seen["tools"], [{"type": "function"}])

    def test_unsupported_model_is_reported(self):
        FakeOllama.mode = "unsupported"
        with self.assertRaises(ToolsUnsupported):
            self.brain.chat_tools([], [])


class Window(HttpCase):
    __test__ = True

    @classmethod
    def make_session(cls):
        s, cls.app = make_session()
        h, cls.pc, _ = setup_hands()
        s.hands = cls.app.c.hands = h
        h.on_change = lambda: s.hub.publish("pending", items=h.pending())
        return s

    def call(self, path, **body):
        code, data = self.post(path, body=json.dumps(body).encode())
        return code, json.loads(data)

    def test_buttons_and_history_over_http(self):
        h = self.session.hands
        q = h.call("open_app", {"name": "calculator"})
        self.assertEqual(self.call("/api/actions")[1]["pending"][0]["what"], "Open Calculator")
        self.assertEqual(self.session.status()["pending"][0]["id"], q["id"])
        self.assertEqual(self.call("/api/approve", id=q["id"], yes=True)[1], {"ok": True})
        self.assertEqual(self.pc.did[-1], ("launch", "calc"))
        self.assertEqual(self.call("/api/actions")[1]["pending"], [])
        self.assertEqual(self.call("/api/actions")[1]["history"][0]["event"], "done")

    def test_no_button_and_bad_ids(self):
        q = self.session.hands.call("open_website", {"url": "https://example.com"})
        n = len(self.pc.did)
        self.assertTrue(self.call("/api/approve", id=q["id"], yes=False)[1]["ok"])
        self.assertEqual(len(self.pc.did), n)
        self.assertFalse(self.call("/api/approve", id=q["id"], yes=True)[1]["ok"])     # already answered
        self.assertEqual(self.call("/api/approve", id="x", yes=True)[0], 400)

    def test_approving_needs_the_secret(self):
        q = self.session.hands.call("open_app", {"name": "paint"})
        n = len(self.pc.did)
        self.assertEqual(self.post("/api/approve", body=json.dumps({"id": q["id"], "yes": True}).encode(),
                                   headers={"X-Claire-Token": "wrong"})[0], 403)
        self.assertEqual(self.req("GET", "/api/approve")[0], 404)
        self.assertEqual(len(self.pc.did), n)
        self.session.hands.deny(q["id"])

    def test_spoken_yes_and_follow_up(self):
        s = self.session
        self.assertFalse(s._follow_up())
        s.hands.call("open_app", {"name": "notepad"})
        self.assertTrue(s._follow_up())                          # hands-free listens for the answer without "Hey Claire"
        n = len(self.pc.did)
        s._answer("yes please", spoken=True)
        self.assertEqual(len(self.pc.did), n + 1)
        self.assertFalse(s._follow_up())

    def test_page_has_the_question_card_and_actions_tab(self):
        html = web.PAGE.read_text(encoding="utf-8")
        for needle in ('id="ask"', 'id="tabHands"', "/api/approve", "/api/actions"):
            self.assertIn(needle, html)
        self.assertNotIn("innerHTML", html)


class Settings(unittest.TestCase):
    def test_defaults_are_safe(self):
        t = config.DEFAULTS["tools"]
        self.assertTrue(t["enabled"])
        self.assertEqual(t["always"], [])
        for risky in ("cmd", "powershell", "regedit", "terminal"):
            self.assertNotIn(risky, t["apps"])
            self.assertNotIn(risky, t["apps"].values())


if __name__ == "__main__":
    unittest.main()
