"""The check tool, and guards on the Windows launcher scripts (which can't be run here, so they are linted)."""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claire import config, doctor                                   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BATS = ["make_env", "setup_claire", "setup_voice", "start_claire", "window", "studio", "doctor", "link"]


def cfg_offline():
    c = config.load()
    c["ollama_url"] = "http://127.0.0.1:9"                           # nothing listens there: fast "not running"
    return c


class Doctor(unittest.TestCase):
    def rows(self, has=None):
        with mock.patch.object(doctor, "_has", has or doctor._has):
            return doctor.checks(cfg_offline())

    def test_every_row_is_well_formed(self):
        rows = self.rows()
        self.assertGreaterEqual(len(rows), 8)
        for status, what, detail in rows:
            self.assertIn(status, (doctor.OK, doctor.WARN, doctor.FAIL))
            self.assertTrue(what and detail)

    def test_missing_voice_package_says_what_to_do(self):
        rows = self.rows(has=lambda m: m != "kokoro_onnx")
        row = [r for r in rows if "kokoro-onnx" in r[1]][0]
        self.assertEqual(row[0], doctor.FAIL)
        self.assertIn("setup_voice.bat", row[2])
        self.assertTrue(all(r[0] == doctor.OK for r in rows if "faster-whisper" in r[1]))

    def test_optional_edge_voices_are_only_a_warning(self):
        rows = self.rows(has=lambda m: m != "edge_tts")
        self.assertEqual([r[0] for r in rows if "edge-tts" in r[1]], [doctor.WARN])

    def test_too_new_python_is_called_out_with_the_fix(self):
        with mock.patch.object(sys, "version_info", (3, 15, 0, "final", 0)):
            row = [r for r in self.rows() if r[1] == "Python version"][0]
        self.assertEqual(row[0], doctor.FAIL)
        self.assertIn("3.12", row[2])
        self.assertIn("3.15.0", row[2])

    def test_supported_python_passes(self):
        with mock.patch.object(sys, "version_info", (3, 12, 4, "final", 0)):
            row = [r for r in self.rows() if r[1] == "Python version"][0]
        self.assertEqual(row[0], doctor.OK)

    def test_missing_model_files_are_reported_with_their_path(self):
        c = cfg_offline()
        c["voice"]["kokoro_model"] = "voices/definitely-missing.onnx"
        with mock.patch.object(doctor, "_has", lambda m: True):
            rows = doctor.checks(c)
        row = [r for r in rows if r[1] == "Kokoro voice model"][0]
        self.assertEqual(row[0], doctor.FAIL)
        self.assertIn("definitely-missing.onnx", row[2])

    def test_offline_brain_is_a_failure_not_a_crash(self):
        row = [r for r in self.rows() if r[1] == "Brain (Ollama)"][0]
        self.assertEqual(row[0], doctor.FAIL)

    def test_report_tells_you_the_next_step(self):
        text = doctor.report([(doctor.FAIL, "x", "broken"), (doctor.OK, "y", "fine")])
        self.assertIn("✗", text)
        self.assertIn("1 thing(s) need fixing", text)
        self.assertIn("in place", doctor.report([(doctor.OK, "y", "fine")]))


class Launchers(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_bytes()

    def test_each_bat_has_an_identical_shareable_txt_copy(self):
        for n in BATS:
            self.assertTrue((ROOT / f"{n}.bat").exists(), n)
            self.assertEqual(self.read(f"{n}.bat"), self.read(f"{n}.bat.txt"), f"{n}.bat and {n}.bat.txt differ")

    def test_windows_friendly_files(self):
        for n in BATS:
            data = self.read(f"{n}.bat")
            data.decode("ascii")                                      # plain ASCII only
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), f"{n}.bat must use Windows line endings")
            self.assertIsNone(re.search(r"(?m)^\s*:\w", data.decode()), f"{n}.bat uses labels, which break easily")

    def test_python_limit_is_never_dropped(self):
        """Her voice packages are known to install on Python 3.10 to 3.13 only; a newer Python must not be used silently."""
        text = self.read("make_env.bat").decode()
        self.assertIn("(3,10)<=sys.version_info[:2]<=(3,13)", text)
        self.assertIn("3.12", text)
        for n in ("setup_claire", "setup_voice"):
            self.assertIn("call make_env.bat", self.read(f"{n}.bat").decode())

    def test_every_launcher_prefers_her_own_python(self):
        for n in ("start_claire", "window", "studio", "doctor", "link"):
            text = self.read(f"{n}.bat").decode()
            self.assertIn('if exist ".venv\\Scripts\\python.exe" set "PY=.venv\\Scripts\\python.exe"', text, n)
            self.assertIn('"%PY%" -m claire', text, n)
            self.assertIsNone(re.search(r"(?m)^python ", text), f"{n}.bat still calls the system Python directly")

    def test_voice_setup_stops_loudly_when_pip_fails(self):
        text = self.read("setup_voice.bat").decode()
        self.assertIsNotNone(re.search(r"if errorlevel 1 \(.*did not install", text))
        self.assertLess(text.index("kokoro-onnx"), text.index("if errorlevel 1"))

    def test_no_quoted_program_at_the_start_of_a_for_f_command(self):
        """cmd mangles `for /f ... in (`"prog" "arg"`)`; the model-name lookup must not do that."""
        for n in BATS:
            for line in self.read(f"{n}.bat").decode().splitlines():
                self.assertIsNone(re.search(r"in \(`\"", line), f"{n}.bat: {line}")

    def test_venv_is_not_committed(self):
        self.assertIn(".venv/", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
