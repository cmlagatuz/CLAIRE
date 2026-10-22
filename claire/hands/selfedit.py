"""She can improve her own code — carefully. The path is always the same:
  propose (nothing changes) → her whole test-suite runs on a COPY → you see the diff and say yes → applied, with a
  backup → one command to undo.  Her safety rules, the launchers, your settings and your data are off limits."""
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .files import Refused

ALLOWED = ("claire/", "tests/", "docs/", "README.md", "ROADMAP.md", "identity.md")
EXTS = {".py", ".html", ".md"}
# her safety rules and everything that could be used to weaken them — only Carl edits these, by hand
PROTECTED = ("claire/hands/", "tests/test_phase4.py", "tests/test_hands2.py", "tests/test_devices.py", "tests/test_knowledge.py", "tests/test_companion.py", "claire/health.py", "claire/link.py", "claire/companion.py", "claire/web.py", "claire/cli.py", "claire/config.py")
MAX_BYTES = 200_000
IGNORE = shutil.ignore_patterns(".venv", ".git", "data", "voices", "__pycache__", "*.pyc", "docs")


def run_tests(tree):
    """Run her tests inside `tree` (a copy). Returns (passed, last lines of output)."""
    try:
        r = subprocess.run([sys.executable, "-W", "ignore", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=tree, capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired:
        return False, "the tests took too long"
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:])
    return r.returncode == 0, tail


class SelfEdit:
    def __init__(self, root, data_dir, runner=run_tests):
        self.root = Path(root).resolve()
        self.dir = Path(data_dir) / "proposals"
        self.backups = Path(data_dir) / "backups"
        self.runner = runner
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---- path rules ---------------------------------------------------------------------
    def rel(self, path, for_write=True):
        s = str(path or "").strip().replace("\\", "/")
        if not s or s.startswith("/") or ":" in s or "\0" in s or any(p in ("..", "") for p in s.split("/")):
            raise Refused("I need a path inside my own folder, like claire/core.py.")
        if not (s.startswith(ALLOWED[:3]) or s in ALLOWED[3:]):
            raise Refused("I only work on my own code (claire/, tests/, docs/) and my README, ROADMAP and identity.")
        if Path(s).suffix.lower() not in EXTS:
            raise Refused("I only edit .py, .html and .md files.")
        if for_write and s.startswith(PROTECTED):
            raise Refused("That one protects my safety rules, so only you can change it, by hand.")
        full = (self.root / s)
        real = full.resolve()
        if self.root not in real.parents:
            raise Refused("That path leads outside my folder.")
        return s, real

    # ---- reading ------------------------------------------------------------------------
    def read(self, path):
        s, real = self.rel(path, for_write=False)
        if not real.is_file():
            raise Refused("I can't find that file.")
        text = real.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= 12000 else text[:12000] + f"\n…(cut; {len(text)} characters in all)"

    # ---- proposals ----------------------------------------------------------------------
    def _path(self, pid):
        try:
            n = int(pid)
        except (TypeError, ValueError):
            raise Refused("Which change? I need its number.")
        return self.dir / f"{n}.json", n

    def load(self, pid):
        p, _ = self._path(pid)
        if not p.exists():
            raise Refused("I don't have a change with that number.")
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, prop):
        (self.dir / f"{prop['id']}.json").write_text(json.dumps(prop, ensure_ascii=False, indent=1), encoding="utf-8")

    def list(self):
        out = []
        for f in self.dir.glob("*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                pass
        return sorted(out, key=lambda p: p["id"])

    def propose(self, path, old, new, reason):
        """Prepare a change and test it on a copy. Nothing real is touched."""
        s, real = self.rel(path)
        old, new = str(old or ""), str(new if new is not None else "")
        creating = not real.exists()
        if creating and old:
            raise Refused("That file doesn't exist; to make a new file leave 'old' empty.")
        if not creating and not old:
            raise Refused("To change a file, give me the exact text to replace ('old').")
        before = "" if creating else real.read_text(encoding="utf-8")
        if not creating:
            if before.count(old) != 1:
                raise Refused("The text to replace must appear exactly once in the file "
                              f"(it appears {before.count(old)} times). Read the file and try again.")
            after = before.replace(old, new, 1)
        else:
            after = new
        if len(after.encode()) > MAX_BYTES:
            raise Refused("That file would be too big.")
        if after == before:
            raise Refused("That wouldn't change anything.")
        if s.endswith(".py"):
            try:
                compile(after, s, "exec")
            except SyntaxError as e:
                raise Refused(f"That code has a syntax error on line {e.lineno}: {e.msg}.")
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{s}", f"b/{s}", n=2))
        plus = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        minus = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        tmp = Path(tempfile.mkdtemp(prefix="claire-test-"))
        try:
            tree = tmp / "tree"
            shutil.copytree(self.root, tree, ignore=IGNORE)
            target = tree / s
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(after, encoding="utf-8")
            ok, tail = self.runner(tree)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        ids = [p["id"] for p in self.list()]
        prop = {"id": max(ids, default=0) + 1, "path": s, "reason": str(reason or "")[:300], "created": creating,
                "base": hashlib.sha256(before.encode()).hexdigest(), "after": after, "diff": diff,
                "plus": plus, "minus": minus, "tests_ok": bool(ok), "tests": tail[-600:],
                "status": "ready" if ok else "failed", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self._save(prop)
        return prop

    # ---- applying & undoing -------------------------------------------------------------
    def check_ready(self, pid):
        prop = self.load(pid)
        s, real = self.rel(prop["path"])                     # the rules are checked again at apply time
        if prop["status"] != "ready" or not prop["tests_ok"]:
            raise Refused(f"Change #{prop['id']} can't be applied (it is {prop['status']}).")
        now = real.read_text(encoding="utf-8") if real.exists() else ""
        if hashlib.sha256(now.encode()).hexdigest() != prop["base"]:
            raise Refused(f"{s} has changed since I prepared change #{prop['id']}; I need to prepare it again.")
        return prop, real

    def apply(self, pid):
        prop, real = self.check_ready(pid)
        if not prop["created"]:
            b = self.backups / str(prop["id"]) / prop["path"]
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(real, b)
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(prop["after"], encoding="utf-8")
        prop["status"] = "applied"
        self._save(prop)
        return prop

    def undo(self, pid=None):
        if pid in (None, ""):
            done = [p for p in self.list() if p["status"] == "applied"]
            if not done:
                raise Refused("There is nothing of mine to undo.")
            pid = done[-1]["id"]
        prop = self.load(pid)
        s, real = self.rel(prop["path"])
        if prop["status"] != "applied":
            raise Refused(f"Change #{prop['id']} isn't applied.")
        if not real.exists() or real.read_text(encoding="utf-8") != prop["after"]:
            raise Refused(f"{s} was changed again after that, so I won't undo over your newer work.")
        if prop["created"]:
            real.unlink()
        else:
            shutil.copy2(self.backups / str(prop["id"]) / prop["path"], real)
        prop["status"] = "undone"
        self._save(prop)
        return prop
