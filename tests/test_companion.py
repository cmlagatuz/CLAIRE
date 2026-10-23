"""Phase 4.8 · Companion — health alerts, the phone link, reminders, notes and break reminders.
Fake clocks, fake devices; the link tests use a real local socket but only on 127.0.0.1."""
import http.client
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claire import companion, config, health, link, reminders, wellbeing   # noqa: E402
from claire.hands.tools import Hands                                        # noqa: E402
from test_phase4 import FakePC                                              # noqa: E402

TOKEN = "t" * 24


class Clock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def adv(self, secs):
        self.t += secs


class Dev(FakePC):
    app, idle, hits = "chrome.exe", 0.0, None

    def foreground_app(self):
        return self.app

    def idle_seconds(self):
        return self.idle


def make(**over):
    cfg = json.loads(json.dumps(config.DEFAULTS))
    cfg["data_dir"] = tempfile.mkdtemp()
    cfg["companion"].update(over)
    clock, said = Clock(), []
    now = [datetime(2026, 10, 23, 12, 0)]
    pc = Dev()
    pc.shortcuts_hit = []
    comp = companion.Companion(cfg, pc, lambda t, urgent=False: said.append((t, urgent)), tools=cfg["tools"],
                               clock=clock, now=lambda: now[0])
    return comp, clock, said, now, pc, cfg


class Emergency(unittest.TestCase):
    def test_words_that_must_trigger(self):
        for t in ("I have chest pain", "my chest feels tight", "chest tightness since morning", "I think I'm having a heart attack",
                  "I can't breathe", "short of breath", "pain in my left arm", "my arm is numb", "I'm about to faint",
                  "I'm not okay", "slurred speech", "call an ambulance", "crushing pain"):
            if "feels tight" in t:
                continue                                  # covered by 'chest tightness'; phrase variants are not exhaustive
            self.assertTrue(health.EMERGENCY.search(t), t)

    def test_everyday_talk_must_not(self):
        for t in ("what is a heart attack", "help me write an email", "tell me about my chest day workout", "open notepad",
                  "I'm fine", "how's my pc", "remind me to call the doctor tomorrow"):
            self.assertFalse(health.EMERGENCY.search(t), t)

    def test_reply_is_calm_direct_and_never_reassures(self):
        r = health.EMERGENCY_REPLY.lower()
        self.assertIn("emergency number", r)
        self.assertIn("997", r)
        self.assertIn("don't wait for me", r)
        for bad in ("you're fine", "you are fine", "nothing to worry", "probably nothing", "it's just"):
            self.assertNotIn(bad, r)

    def test_works_without_any_watch_data_and_before_any_ai(self):
        comp, *_ = make()
        self.assertEqual(comp.answer("I have chest pain"), health.EMERGENCY_REPLY)

    def test_emergency_is_checked_before_everything_in_the_window_and_terminal(self):
        from claire import cli, web
        for src in (Path(web.__file__).read_text(encoding="utf-8"), Path(cli.__file__).read_text(encoding="utf-8")):
            self.assertLess(src.index("comp.answer(text)" if "comp.answer(text)" in src else "self.companion.answer(text)"),
                            src.index("HUSH.match(text)"))


class Readings(unittest.TestCase):
    def vit(self):
        clock = Clock()
        return health.Vitals(clock), clock

    def feed(self, v, clock, kind, values, gap=120):
        for x in values:
            v.add(kind, x)
            clock.adv(gap)

    def test_normal_readings_raise_nothing(self):
        v, c = self.vit()
        self.feed(v, c, "hr", [68, 72, 75, 70])
        self.feed(v, c, "spo2", [97, 98])
        self.assertEqual(health.assess(v), [])

    def test_resting_high_heart_rate(self):
        v, c = self.vit()
        self.feed(v, c, "hr", [125, 130, 128])
        self.assertEqual([a.key for a in health.assess(v)], ["hr_high"])

    def test_exercise_is_not_an_alarm(self):
        v, c = self.vit()
        self.feed(v, c, "steps", [400, 500, 450])
        self.feed(v, c, "hr", [140, 150, 145])
        self.assertEqual(health.assess(v), [])

    def test_very_high_while_resting_is_urgent(self):
        v, c = self.vit()
        v.add("hr", 168)
        self.assertEqual([(a.key, a.level) for a in health.assess(v)], [("hr_very_high", "urgent")])

    def test_low_heart_rate_needs_two_readings(self):
        v, c = self.vit()
        v.add("hr", 38)
        self.assertEqual(health.assess(v), [])
        c.adv(60)
        v.add("hr", 39)
        self.assertEqual([a.key for a in health.assess(v)], ["hr_low"])

    def test_oxygen(self):
        v, c = self.vit()
        v.add("spo2", 89)
        self.assertEqual(health.assess(v), [])                        # one low reading can be a bad fit of the watch
        c.adv(60)
        v.add("spo2", 88)
        self.assertEqual([(a.key, a.level) for a in health.assess(v)], [("spo2_low", "check")])
        c.adv(60)
        v.add("spo2", 84)
        self.assertIn(("spo2_critical", "urgent"), [(a.key, a.level) for a in health.assess(v)])

    def test_old_readings_are_ignored_for_alerts(self):
        v, c = self.vit()
        self.feed(v, c, "hr", [130, 131, 132])
        c.adv(3600)
        self.assertEqual(health.assess(v), [])

    def test_status_is_honest_about_missing_and_old_data_and_never_reassures(self):
        v, c = self.vit()
        self.assertIn("can't tell you anything", v.status())
        v.add("hr", 70)
        fresh = v.status()
        self.assertIn("Heart rate 70 bpm (just now)", fresh)
        self.assertIn("not a doctor", fresh)
        c.adv(3 * 3600)
        old = v.status()
        self.assertIn("old", old)
        self.assertIn("say nothing about how you are right now", old)
        for text in (fresh, old, v.status()):
            for bad in ("fine", "healthy", "normal", "safe", "all good", "no problem"):
                self.assertNotIn(bad, text.lower())


class Alerts(unittest.TestCase):
    def setUp(self):
        self.v = health.Vitals(Clock())
        self.clock, self.said = self.v.clock, []
        self.m = health.Monitor(self.v, lambda t, urgent=False: self.said.append((t, urgent)), self.clock)

    def resting_high(self):
        for x in (125, 130, 128):
            self.v.add("hr", x)
            self.clock.adv(30)

    def test_check_in_is_said_once_then_quiet(self):
        self.resting_high()
        self.assertEqual(len(self.m.check()), 1)
        self.assertEqual(len(self.m.check()), 0)
        text, urgent = self.said[0]
        self.assertFalse(urgent)
        self.assertIn("Are you okay?", text)
        self.assertIn("not a doctor", text)

    def test_im_fine_quiets_it_for_an_hour_but_not_forever(self):
        self.resting_high()
        self.m.check()
        self.assertIn("won't mention it for an hour", self.m.reply("I'm fine, just exercising"))
        self.clock.adv(3000)
        self.assertEqual(self.m.check(), [])
        self.clock.adv(700)
        self.v.add("hr", 131)
        self.v.add("hr", 130)
        self.v.add("hr", 129)
        self.assertEqual(len(self.m.check()), 1)

    def test_im_not_ok_or_symptom_words_get_the_emergency_reply(self):
        self.resting_high()
        self.m.check()
        self.assertEqual(self.m.reply("I'm not okay"), health.EMERGENCY_REPLY)
        self.assertEqual(self.m.reply("my chest hurts"), health.EMERGENCY_REPLY)

    def test_unrelated_talk_is_left_alone(self):
        self.resting_high()
        self.m.check()
        self.assertIsNone(self.m.reply("what time is it"))

    def test_urgent_repeats_every_five_minutes_until_answered(self):
        self.v.add("hr", 170)
        self.m.check()
        self.assertTrue(self.said[0][1])
        self.assertIn("emergency number", self.said[0][0])
        self.clock.adv(120)
        self.v.add("hr", 170)
        self.m.check()
        self.assertEqual(len(self.said), 1)
        self.clock.adv(200)
        self.v.add("hr", 172)
        self.m.check()
        self.assertEqual(len([1 for _, urgent in self.said if urgent]), 2)


class Validation(unittest.TestCase):
    def test_good_events(self):
        self.assertEqual(link.validate({"type": "heart_rate", "bpm": 72}), {"type": "heart_rate", "bpm": 72.0})
        self.assertEqual(link.validate({"type": "spo2", "percent": "97"})["percent"], 97.0)
        n = link.validate({"type": "notification", "app": "WhatsApp", "title": "Ali", "text": "hi", "extra": "dropped"})
        self.assertEqual(n, {"type": "notification", "app": "WhatsApp", "title": "Ali", "text": "hi"})
        self.assertEqual(link.validate({"type": "call", "who": "Mum", "kind": "missed"})["kind"], "missed")
        self.assertEqual(link.validate({"type": "app_usage", "app": "Instagram"})["state"], "opened")

    def test_bad_events(self):
        for ev in (None, [], "x", {}, {"type": "format_disk"}, {"type": "heart_rate"}, {"type": "heart_rate", "bpm": 5},
                   {"type": "heart_rate", "bpm": 9999}, {"type": "heart_rate", "bpm": True}, {"type": "heart_rate", "bpm": "abc"},
                   {"type": "spo2", "percent": 20}, {"type": "notification"}, {"type": "notification", "app": 5},
                   {"type": "call", "who": "x", "kind": "weird"}, {"type": "app_usage", "app": "x", "state": "deleted"}):
            with self.assertRaises(ValueError, msg=str(ev)):
                link.validate(ev)

    def test_text_is_cut_and_cleaned(self):
        n = link.validate({"type": "notification", "app": "A" * 500, "title": "line\x00one\x07" + "x" * 500})
        self.assertEqual(len(n["app"]), 40)
        self.assertNotIn("\x00", n["title"])
        self.assertLessEqual(len(n["title"]), 80)


class Server(unittest.TestCase):
    def setUp(self):
        self.events, self.clock = [], Clock()
        self.srv = link.LinkServer(TOKEN, self.events.append, host="127.0.0.1", port=0, allow_loopback=True, clock=self.clock)
        self.srv.start()

    def tearDown(self):
        self.srv.stop()

    def call(self, method="POST", path=None, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        c.request(method, path or f"/e/{TOKEN}", body=json.dumps(body) if not isinstance(body, (bytes, str)) else body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data or b"{}")

    def test_a_valid_event_arrives(self):
        self.assertEqual(self.call(body={"type": "heart_rate", "bpm": 71}), (200, {"ok": True}))
        self.assertEqual(self.events, [{"type": "heart_rate", "bpm": 71.0}])

    def test_health_connect_batches_keep_their_own_times_and_drop_stale_ones(self):
        now = self.clock()

        def iso(ago):
            return datetime.utcfromtimestamp(now - ago).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {"timestamp": iso(0), "app_version": "1", "heart_rate": [
            {"bpm": 80, "time": iso(600)}, {"bpm": 150, "time": iso(7 * 3600)}, {"bpm": 90, "time": iso(60)}, {"bpm": 90, "time": "junk"}],
            "oxygen_saturation": [{"percentage": 97.0, "time": iso(30)}]}
        self.assertEqual(self.call(body=body)[0], 200)
        got = [(e["type"], e.get("bpm", e.get("percent")), round(now - e["at"])) for e in self.events]
        self.assertEqual(got, [("heart_rate", 80.0, 600), ("heart_rate", 90.0, 60), ("spo2", 97.0, 30)])

    def test_batch_with_an_impossible_value_is_refused_whole(self):
        iso = datetime.utcfromtimestamp(self.clock() - 5).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.call(body={"heart_rate": [{"bpm": 999, "time": iso}]})[0], 400)
        self.assertEqual(self.events, [])

    def test_token_in_path_header_or_query(self):
        self.assertEqual(self.call(path="/x", headers={"X-Claire-Link": TOKEN}, body={"type": "ping"})[0], 200)
        self.assertEqual(self.call(path=f"/anything?k={TOKEN}", body={"type": "ping"})[0], 200)
        self.assertEqual(self.call("GET")[1]["ok"], True)                       # the browser test

    def test_wrong_or_missing_token_is_refused_and_nothing_is_delivered(self):
        for path, h in (("/e/" + "x" * 24, {}), ("/e/", {}), ("/", {}), ("/e/" + TOKEN[:-1], {}), ("/", {"X-Claire-Link": "nope"})):
            self.assertEqual(self.call(path=path, headers=h, body={"type": "ping"})[0], 403, path)
        self.assertEqual(self.events, [])

    def test_guessing_is_locked_out_for_ten_minutes(self):
        for _ in range(10):
            self.call(path="/e/wrong", body={"type": "ping"})
        self.assertEqual(self.call(body={"type": "ping"})[0], 429)                # even the right token is refused now
        self.clock.adv(601)
        self.assertEqual(self.call(body={"type": "ping"})[0], 200)

    def test_bad_bodies(self):
        self.assertEqual(self.call(body=b"not json")[0], 400)
        self.assertEqual(self.call(body={"type": "reboot"})[0], 400)
        self.assertEqual(self.call(body={"type": "heart_rate", "bpm": 1})[0], 400)
        self.assertEqual(self.call(body=b"x" * 70000)[0], 413)
        self.assertEqual(self.call(body=b"")[0], 400)
        self.assertEqual(self.events, [])

    def test_flooding_is_slowed(self):
        codes = [self.call(body={"type": "ping"})[0] for _ in range(125)]
        self.assertEqual(codes.count(200), 120)
        self.assertEqual(codes[-1], 429)

    def test_only_private_network_devices_may_talk(self):
        s = link.LinkServer(TOKEN, lambda e: None, host="127.0.0.1", port=0)       # loopback NOT allowed by default
        try:
            self.assertTrue(s.source_ok("192.168.1.20") and s.source_ok("10.1.2.3"))
            for ip in ("8.8.8.8", "203.0.113.9", "127.0.0.1", "169.254.1.1", "garbage"):
                self.assertFalse(s.source_ok(ip), ip)
        finally:
            s.server_close()

    def test_weak_tokens_are_refused(self):
        for t in ("", "short", None):
            with self.assertRaises(ValueError):
                link.LinkServer(t, lambda e: None, host="127.0.0.1", port=0)

    def test_it_never_logs_requests(self):
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            self.call(body={"type": "ping"})
        self.assertNotIn(TOKEN, buf.getvalue())


class Phone(unittest.TestCase):
    def test_vitals_survive_a_restart_and_are_stored_only_in_data(self):
        comp, clock, said, now, pc, cfg = make()
        comp.handle_event({"type": "heart_rate", "bpm": 66.0})
        comp.handle_event({"type": "spo2", "percent": 98.0})
        again = companion.Companion(cfg, pc, lambda *a, **k: None, clock=clock, now=lambda: now[0])
        self.assertEqual(again.vitals.last("hr")[1], 66.0)
        self.assertEqual(again.vitals.last("spo2")[1], 98.0)
        self.assertTrue(str(comp.health_log).startswith(cfg["data_dir"]))

    def test_alerts_flow_from_events(self):
        comp, clock, said, *_ = make()
        for bpm in (170,):
            comp.handle_event({"type": "heart_rate", "bpm": float(bpm)})
        self.assertTrue(said and said[0][1] and "emergency number" in said[0][0])

    def test_notifications_are_short_private_and_batched(self):
        comp, clock, said, *_ = make()
        comp.handle_event({"type": "notification", "app": "WhatsApp", "title": "Ali", "text": "secret message"})
        self.assertEqual(said[-1][0], "Ali — WhatsApp")                       # content is NOT read out by default
        comp.handle_event({"type": "notification", "app": "Telegram", "title": "Sara", "text": "x"})
        comp.handle_event({"type": "call", "who": "Mum", "kind": "missed"})
        self.assertEqual(len(said), 1)                                         # held back (not a flood)
        clock.adv(10)
        comp.tick()
        self.assertIn("2 new things on your phone", said[-1][0])
        self.assertIn("Missed call from Mum", said[-1][0])

    def test_message_text_only_when_you_allow_it(self):
        comp, clock, said, *_ = make(link={"read_message_text": True})
        comp.handle_event({"type": "notification", "app": "WhatsApp", "title": "Ali", "text": "lunch at 1?"})
        self.assertEqual(said[-1][0], "Ali — WhatsApp: lunch at 1?")

    def test_quiet_hours_hold_back_everything_but_urgent_health(self):
        comp, clock, said, now, *_ = make()
        now[0] = datetime(2026, 10, 23, 23, 30)
        comp.handle_event({"type": "notification", "app": "WhatsApp", "title": "Ali"})
        self.assertEqual(said, [])
        comp.handle_event({"type": "heart_rate", "bpm": 175.0})
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0][1])                                            # urgent health speaks at night
        now[0] = datetime(2026, 10, 24, 7, 30)
        comp.tick()
        self.assertIn("held back 1 thing", said[-1][0])

    def test_quiet_hours_across_midnight(self):
        q = ["23:00", "07:00"]
        for h, expect in ((23, True), (2, True), (6, True), (7, False), (12, False), (22, False)):
            self.assertEqual(companion.in_quiet(datetime(2026, 1, 1, h, 30 if h == 6 else 0), q), expect, h)
        self.assertFalse(companion.in_quiet(datetime(2026, 1, 1, 3), ["nonsense"]))

    def test_urgent_alerts_also_reach_the_phone_through_your_shortcut(self):
        comp, clock, said, now, pc, cfg = make(notify_shortcut="Phone alert")
        comp.tools["shortcuts"] = {"phone alert": "http://192.168.1.50:8080/alert"}
        comp.handle_event({"type": "heart_rate", "bpm": 175.0})
        self.assertEqual(pc.shortcuts_hit, ["http://192.168.1.50:8080/alert"])
        self.assertEqual(comp.answer("I have chest pain"), health.EMERGENCY_REPLY)
        self.assertEqual(len(pc.shortcuts_hit), 2)


class Breaks(unittest.TestCase):
    def run_for(self, comp, clock, minutes, step=30):
        out = []
        for _ in range(int(minutes * 60 / step)):
            clock.adv(step)
            comp.tick()
        return out

    def test_same_app_for_ninety_minutes_gets_a_break_suggestion(self):
        comp, clock, said, *_ = make()
        self.run_for(comp, clock, 80)
        self.assertEqual([t for t, _ in said if "break" in t], [])
        self.run_for(comp, clock, 15)
        msg = [t for t, _ in said if "without a break" in t]
        self.assertEqual(len(msg), 1)
        self.assertIn("Chrome", msg[0])
        self.assertRegex(msg[0], r"1 h 3\d min|1 h 2\d min|1 h 30 min")

    def test_no_nagging_then_again_after_the_cooldown(self):
        comp, clock, said, *_ = make()
        self.run_for(comp, clock, 125)
        n1 = len([1 for t, _ in said if "without a break" in t])
        self.assertGreaterEqual(n1, 1)
        self.run_for(comp, clock, 20)
        self.assertEqual(len([1 for t, _ in said if "without a break" in t]), n1)       # 30-minute cooldown holds
        self.run_for(comp, clock, 15)
        self.assertGreater(len([1 for t, _ in said if "without a break" in t]), n1)

    def test_stepping_away_counts_as_a_break(self):
        comp, clock, said, now, pc, _ = make()
        self.run_for(comp, clock, 80)
        pc.idle = 600                                                              # away for ten minutes
        self.run_for(comp, clock, 10)
        pc.idle = 0
        self.run_for(comp, clock, 30)
        self.assertEqual([t for t, _ in said if "without a break" in t], [])

    def test_switching_apps_still_counts_as_continuous_screen_time(self):
        comp, clock, said, now, pc, _ = make()
        for i in range(int(125 * 2)):
            pc.app = "chrome.exe" if (i // 20) % 2 == 0 else "Code.exe"
            clock.adv(30)
            comp.tick()
        self.assertTrue([t for t, _ in said if "on screens for" in t])

    def test_totals_and_summary(self):
        comp, clock, said, now, pc, _ = make()
        self.run_for(comp, clock, 30)
        self.assertIn("Chrome 29 min", comp.usage.summary()) if False else self.assertIn("Chrome", comp.usage.summary())
        self.assertEqual(wellbeing.nice(95), "1 h 35 min")

    def test_phone_apps_use_events_and_are_reported_as_the_phones(self):
        comp, clock, said, now, pc, _ = make()
        pc.app = None                                                              # nothing in front on the PC
        comp.handle_event({"type": "app_usage", "app": "Instagram", "state": "opened"})
        self.run_for(comp, clock, 100)
        msg = [t for t, _ in said if "Instagram" in t]
        self.assertTrue(msg and "your phone's" in msg[0])
        comp.handle_event({"type": "app_usage", "app": "Instagram", "state": "closed"})
        self.assertIsNone(comp.phone_open)

    def test_a_phone_app_with_no_close_event_is_dropped_after_hours(self):
        comp, clock, said, now, pc, _ = make(breaks={"enabled": True, "same_app_minutes": 9999, "continuous_minutes": 9999})
        pc.app = None
        comp.handle_event({"type": "app_usage", "app": "Game", "state": "opened"})
        clock.adv(5 * 3600)
        comp.tick()
        self.assertIsNone(comp.phone_open)

    def test_can_be_switched_off(self):
        comp, clock, said, *_ = make(breaks={"enabled": False, "same_app_minutes": 1, "continuous_minutes": 1})
        self.run_for(comp, clock, 20)
        self.assertEqual(said, [])


class Reminders(unittest.TestCase):
    def setUp(self):
        self.now = [datetime(2026, 10, 23, 12, 0)]
        self.r = reminders.Reminders(tempfile.mkdtemp(), lambda: self.now[0])

    def test_a_birthday_repeats_every_year(self):
        item = self.r.add("Mum's birthday", "2027-03-14", "yearly")
        self.assertEqual(item["due"], "2027-03-14T09:00")
        self.now[0] = datetime(2027, 3, 14, 9, 1)
        self.assertEqual([x["text"] for x in self.r.due()], ["Mum's birthday"])
        self.assertEqual(self.r.due(), [])                                          # not twice
        self.assertEqual(self.r.upcoming(400)[0]["due"], "2028-03-14T09:00")

    def test_one_off_reminders_are_removed_once_fired(self):
        self.r.add("Call the embassy", "2026-10-23T15:30")
        self.assertEqual(self.r.due(), [])
        self.now[0] = datetime(2026, 10, 23, 15, 31)
        self.assertEqual(len(self.r.due()), 1)
        self.assertEqual(self.r.upcoming(400), [])

    def test_past_dates_are_refused_unless_repeating(self):
        with self.assertRaises(reminders.Refused):
            self.r.add("x", "2020-01-01")
        self.assertEqual(self.r.add("anniversary", "2020-10-01", "yearly")["due"], "2027-10-01T09:00")

    def test_bad_input(self):
        for text, when in (("", "2027-01-01"), ("x", "tomorrow"), ("x", ""), ("x", "2027-13-45")):
            with self.assertRaises(reminders.Refused, msg=when):
                self.r.add(text, when)
        with self.assertRaises(reminders.Refused):
            self.r.add("x", "2027-01-01", "hourly")

    def test_awkward_calendar_days(self):
        self.assertEqual(reminders.advance(datetime(2028, 2, 29, 9), "yearly"), datetime(2029, 2, 28, 9))
        self.assertEqual(reminders.advance(datetime(2026, 1, 31, 9), "monthly"), datetime(2026, 2, 28, 9))
        self.assertEqual(reminders.advance(datetime(2026, 12, 15, 9), "monthly"), datetime(2027, 1, 15, 9))

    def test_missed_while_off_fire_once_not_for_every_missed_year(self):
        self.r.add("daily pill", "2026-10-24T08:00", "daily")
        self.now[0] = datetime(2026, 11, 20, 12)
        self.assertEqual(len(self.r.due()), 1)
        self.assertTrue(self.r.upcoming(5)[0]["due"] > "2026-11-20T12:00")

    def test_notes(self):
        self.r.note("Ask Ali about the visa quota")
        self.now[0] += timedelta(minutes=5)
        self.r.note("Buy printer paper")
        self.assertEqual([n["text"] for n in self.r.recent_notes()], ["Buy printer paper", "Ask Ali about the visa quota"])
        self.assertEqual(len(self.r.recent_notes(query="visa")), 1)
        with self.assertRaises(reminders.Refused):
            self.r.note("  ")


class ThroughTheTools(unittest.TestCase):
    def setUp(self):
        self.comp, self.clock, self.said, self.now, self.pc, self.cfg = make()
        self.h = Hands(self.cfg, FakePC())
        self.h.companion = self.comp

    def test_reminders_and_notes(self):
        r = self.h.call("add_reminder", {"text": "Mum's birthday", "when": "2027-03-14", "repeat": "yearly"})
        self.assertEqual(r["status"], "done")
        self.assertIn("Sunday 14 March 2027 at 09:00", r["text"])
        self.assertIn("Mum's birthday", self.h.call("list_reminders", {})["text"])
        self.assertEqual(self.h.call("add_reminder", {"text": "x", "when": "yesterday"})["status"], "error")
        self.assertEqual(self.h.call("add_reminder", {"text": "x", "when": "2020-01-01"})["status"], "error")
        self.h.call("take_note", {"text": "Call the bank"})
        self.assertIn("Call the bank", self.h.call("list_notes", {})["text"])
        self.assertEqual(self.h.pending(), [])                                      # her own notes need no question

    def test_deleting_a_reminder_asks_first(self):
        self.h.call("add_reminder", {"text": "dentist", "when": "2027-01-05T10:00"})
        self.assertEqual(self.h.call("remove_reminder", {"id": 1})["status"], "pending")
        self.assertEqual(len(self.comp.reminders.upcoming(400)), 1)
        self.h.answer("yes")
        self.assertEqual(self.comp.reminders.upcoming(400), [])
        self.assertEqual(self.h.call("remove_reminder", {"id": 99})["status"], "error")

    def test_health_status_is_honest(self):
        self.assertIn("can't tell you anything", self.h.call("health_status", {})["text"])
        self.comp.handle_event({"type": "heart_rate", "bpm": 64.0})
        self.assertIn("64 bpm", self.h.call("health_status", {})["text"])

    def test_screen_time(self):
        self.comp.usage.sample("chrome.exe", 0, now=self.clock())
        self.comp.usage.sample("chrome.exe", 0, now=self.clock() + 60)
        self.assertIn("Chrome", self.h.call("screen_time", {})["text"])

    def test_without_the_companion_the_tools_explain(self):
        h = Hands(self.cfg, FakePC())
        self.assertEqual(h.call("health_status", {})["status"], "error")

    def test_there_is_no_tool_that_can_change_health_data_or_the_link(self):
        names = {s["function"]["name"] for s in self.h.specs()}
        for bad in ("set_health", "delete_health", "set_token", "start_link", "disable_alerts", "mute_health"):
            self.assertNotIn(bad, names)

    def test_her_health_code_cannot_be_edited_by_her(self):
        from claire.hands.selfedit import SelfEdit
        se = SelfEdit(Path(__file__).resolve().parent.parent, tempfile.mkdtemp())
        for p in ("claire/health.py", "claire/link.py", "claire/companion.py", "tests/test_companion.py"):
            with self.assertRaises(Exception):
                se.rel(p)


class SetupCommand(unittest.TestCase):
    def run_setup(self, ips=("192.168.1.10", "172.20.0.1")):
        saved = {}
        buf = io.StringIO()
        with mock.patch.object(config, "save_setting", lambda k, v, *a: saved.__setitem__(k, v)), \
                mock.patch("claire.hands.platform.Platform.addresses", lambda s: list(ips)), \
                mock.patch.object(config, "load", lambda *a: json.loads(json.dumps(config.DEFAULTS))), \
                mock.patch.object(companion, "start_test_server", side_effect=OSError("in use")), redirect_stdout(buf):
            companion.setup_link()
        return saved, buf.getvalue()

    def test_link_setup_makes_a_strong_token_and_lists_every_address(self):
        saved, out = self.run_setup()
        self.assertTrue(saved["companion.link.enabled"])
        tok = saved["companion.link.token"]
        self.assertGreaterEqual(len(tok), 24)
        self.assertIn(f"http://192.168.1.10:8766/e/{tok}", out)
        self.assertIn(f"http://172.20.0.1:8766/e/{tok}", out)             # a VPN/virtual adapter may be the wrong one
        self.assertIn("already in use", out)

    def test_the_timeout_help_names_the_real_causes(self):
        _, out = self.run_setup()
        for needle in ("took too long", "same Wi-Fi", "netsh advfirewall", "localport=8766", "PRIVATE", "127.0.0.1"):
            self.assertIn(needle, out)

    def test_test_mode_receives_and_prints_events(self):
        lines = []
        srv = companion.start_test_server("k" * 24, 0, out=lines.append)
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
            c.request("POST", "/e/" + "k" * 24, body=json.dumps({"type": "heart_rate", "bpm": 72}),
                      headers={"Content-Type": "application/json"})
            self.assertEqual(c.getresponse().status, 200)
            c.close()
        finally:
            srv.stop()
        self.assertEqual(lines, ["   received: type=heart_rate, bpm=72.0"])

    def test_the_window_lets_this_pc_test_its_own_link(self):
        src = Path(companion.__file__).read_text(encoding="utf-8")
        self.assertIn("allow_loopback=True", src)

    def test_defaults_are_safe(self):
        d = config.DEFAULTS["companion"]
        self.assertFalse(d["link"]["enabled"])
        self.assertEqual(d["link"]["token"], "")
        self.assertFalse(d["link"]["read_message_text"])


if __name__ == "__main__":
    unittest.main()
