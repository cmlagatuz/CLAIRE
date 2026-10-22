"""Phase 4.7 · network (read-only), phone (ADB) and shortcuts — a fake network, a fake adb, nothing real is touched."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from claire import config                                           # noqa: E402
from claire.hands import net, phone                                  # noqa: E402
from claire.hands.files import Refused                               # noqa: E402
from claire.hands.tools import Hands                                 # noqa: E402
from test_phase4 import FakePC                                       # noqa: E402

WIN_ARP = FakePC.arp
LINUX_ARP = "? (192.168.1.5) at 11:22:33:44:55:66 [ether] on eth0\n? (10.0.0.9) at de:ad:be:ef:00:01 [ether] on eth0\n"


def make(**tools):
    cfg = json.loads(json.dumps(config.DEFAULTS))
    cfg["data_dir"] = tempfile.mkdtemp()
    cfg["tools"].update(tools)
    pc = FakePC()
    pc.adb_log, pc.adb_out, pc.shortcuts_hit = [], {}, []
    return Hands(cfg, pc), pc


class Network(unittest.TestCase):
    def test_arp_is_read_and_noise_removed(self):
        d = net.parse_arp(WIN_ARP)
        self.assertEqual([x["ip"] for x in d], ["192.168.1.1", "192.168.1.20"])        # no broadcast, no multicast
        self.assertEqual(d[0]["mac"], "aa:bb:cc:00:00:01")
        self.assertEqual([x["ip"] for x in net.parse_arp(LINUX_ARP)], ["10.0.0.9", "192.168.1.5"])
        self.assertEqual(net.parse_arp("8.8.8.8 aa-bb-cc-00-00-01"), [])                # public addresses never listed

    def test_only_home_networks_are_scanned(self):
        self.assertEqual(str(net.lan("192.168.1.10")), "192.168.1.0/24")
        for ip in ("8.8.8.8", "1.1.1.1", "127.0.0.1", "169.254.1.1", "0.0.0.0", "224.0.0.1", "nonsense"):
            with self.assertRaises(Refused, msg=ip):
                net.lan(ip)

    def test_map_then_trust_then_new_devices_are_flagged(self):
        h, pc = make()
        first = h.call("network_map", {})
        self.assertEqual(first["status"], "done")
        self.assertIn("2 devices", first["text"])
        self.assertIn("router", first["text"])
        self.assertIn("don't know yet", first["text"])
        self.assertEqual(str(pc.swept), "192.168.1.0/24")
        self.assertEqual(h.call("network_trust", {})["status"], "pending")               # remembering needs a yes
        self.assertFalse(net.Known(h.cfg["data_dir"]).macs())
        h.answer("yes")
        self.assertEqual(len(net.Known(h.cfg["data_dir"]).macs()), 2)
        self.assertIn("already told me", h.call("network_map", {})["text"])
        pc.arp += "  192.168.1.77          de-ad-be-ef-00-77     dynamic\n"
        again = h.call("network_map", {})["text"]
        self.assertIn("1 I haven't seen before", again)
        self.assertIn("192.168.1.77", again)

    def test_trusting_needs_a_look_first(self):
        h, _ = make()
        self.assertEqual(h.call("network_trust", {})["status"], "error")

    def test_a_public_ip_is_never_swept(self):
        h, pc = make()
        pc.ip = "8.8.8.8"
        self.assertEqual(h.call("network_map", {})["status"], "error")
        pc.ip = "192.168.1.10"

    def test_there_is_no_tool_to_attack_or_disconnect_anything(self):
        names = {s["function"]["name"] for s in make()[0].specs()}
        for bad in ("block_device", "kick", "disconnect_device", "port_scan", "deauth", "scan_ports"):
            self.assertNotIn(bad, names)


class Phone(unittest.TestCase):
    def test_addresses(self):
        self.assertEqual(phone.check_address(" 192.168.1.20:5555 "), "192.168.1.20:5555")
        for a in ("8.8.8.8:5555", "192.168.1.20", "192.168.1.20:0", "192.168.1.20:99999", "host:5555",
                  "192.168.1.20:5555; rm -rf /", "192.168.1.20:5555 -s x", "", None, "127.0.0.1:5555"):
            with self.assertRaises(Refused, msg=str(a)):
                phone.check_address(a)

    def test_battery_and_devices(self):
        self.assertEqual(phone.parse_battery("Current Battery Service state:\n  level: 73\n  scale: 100\n  status: 2\n"),
                         {"percent": 73, "state": "charging"})
        self.assertIsNone(phone.parse_battery("nothing"))
        self.assertEqual(phone.parse_devices("List of devices attached\n192.168.1.20:5555\tdevice\nR58\toffline\n"),
                         [("192.168.1.20:5555", "device"), ("R58", "offline")])

    def test_apps_only_from_the_list_and_well_formed(self):
        apps = {"WhatsApp": "com.whatsapp", "bad": "x; reboot"}
        self.assertEqual(phone.check_app("whatsapp", apps), ("whatsapp", "com.whatsapp"))
        for n in ("camera", "com.whatsapp", "", None, "bad"):
            with self.assertRaises(Refused, msg=str(n)):
                phone.check_app(n, apps)

    def test_status_connect_open_through_the_tools(self):
        h, pc = make()
        pc.adb_out = {"devices": (0, "List of devices attached\n192.168.1.20:5555\tdevice\n"),
                      "shell getprop": (0, "SM-S918B\n"), "shell dumpsys": (0, "level: 60\nscale: 100\nstatus: 3"),
                      "connect": (0, "connected to 192.168.1.20:5555"), "shell monkey": (0, "Events injected: 1")}
        self.assertEqual(h.call("phone_status", {})["text"], "Your SM-S918B is connected. Battery 60%, discharging.")
        self.assertEqual(h.call("phone_connect", {"address": "192.168.1.20:5555"})["status"], "pending")
        self.assertNotIn(["connect", "192.168.1.20:5555"], pc.adb_log)                    # not before the yes
        self.assertIn("Connected", h.answer("yes"))
        self.assertIn(["connect", "192.168.1.20:5555"], pc.adb_log)
        self.assertEqual(h.call("phone_open_app", {"name": "WhatsApp"})["status"], "pending")
        h.answer("yes")
        self.assertIn(["shell", "monkey", "-p", "com.whatsapp", "-c", "android.intent.category.LAUNCHER", "1"], pc.adb_log)

    def test_unlisted_apps_and_bad_addresses_never_reach_adb(self):
        h, pc = make()
        for call in (("phone_open_app", {"name": "banking"}), ("phone_open_app", {"name": "com.evil.app"}),
                     ("phone_connect", {"address": "8.8.8.8:5555"}), ("phone_connect", {"address": "x; reboot"})):
            self.assertEqual(h.call(*call)["status"], "error", call)
        self.assertEqual((pc.adb_log, h.pending()), ([], []))

    def test_missing_adb_explains_what_to_install(self):
        h, pc = make()
        pc.adb_out = None
        r = h.call("phone_status", {})
        self.assertEqual(r["status"], "error")
        self.assertIn("platform-tools", r["text"])


class Shortcuts(unittest.TestCase):
    def test_only_listed_lan_shortcuts_run_and_only_after_a_yes(self):
        h, pc = make(shortcuts={"Buzz my watch": "http://192.168.1.50:8080/buzz", "Lights": "http://localhost:8123/hook"})
        self.assertEqual(h.call("run_shortcut", {"name": "buzz my watch"})["status"], "pending")
        self.assertEqual(pc.shortcuts_hit, [])
        self.assertEqual(h.answer("yes"), "Ran “buzz my watch”.")
        self.assertEqual(pc.shortcuts_hit, ["http://192.168.1.50:8080/buzz"])
        self.assertEqual(h.call("run_shortcut", {"name": "format c"})["status"], "error")
        self.assertEqual(h.call("run_shortcut", {"name": "http://evil.com/x"})["status"], "error")

    def test_shortcuts_pointing_off_the_network_are_refused(self):
        for bad in ("http://evil.com/x", "https://8.8.8.8/x", "file:///c:/x", "http://user@192.168.1.5/x", "ftp://192.168.1.5/x",
                    "http://192.168.1.5@evil.com/x"):
            h, pc = make(shortcuts={"x": bad})
            self.assertEqual(h.call("run_shortcut", {"name": "x"})["status"], "error", bad)
            self.assertEqual(pc.shortcuts_hit, [])

    def test_empty_list_says_how_to_add(self):
        h, _ = make()
        self.assertIn("tools.shortcuts", h.call("run_shortcut", {"name": "x"})["text"])


class OnlyTheRelevantTools(unittest.TestCase):
    def names(self, text, **kw):
        return {s["function"]["name"] for s in make()[0].specs_for(text, **kw)}

    def test_groups(self):
        self.assertIn("network_map", self.names("who is on my wifi"))
        self.assertNotIn("open_app", self.names("who is on my wifi"))
        self.assertIn("open_app", self.names("open notepad"))
        self.assertNotIn("phone_status", self.names("open notepad"))
        self.assertIn("search_documents", self.names("what does my report say about visas"))
        self.assertIn("propose_change", self.names("improve yourself"))
        self.assertGreaterEqual(len(self.names("yes", all_tools=True)), 19)
        self.assertLessEqual(len(self.names("open notepad")), 9)


if __name__ == "__main__":
    unittest.main()
