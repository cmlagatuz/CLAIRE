"""Looking for files, safely. Only her allowed folders are ever searched or opened, and nothing here changes a file."""
import os
import re
import time
from pathlib import Path

# opening these could run code, so she never opens them for you — she tells you where they are instead
UNSAFE = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
          ".wsf", ".wsh", ".hta", ".jar", ".lnk", ".reg", ".dll", ".sys", ".cpl", ".msc", ".gadget", ".appx",
          ".msix", ".application", ".url", ".sh", ".py", ".pyw", ".iso", ".vhd", ".docm", ".xlsm", ".pptm"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "$recycle.bin", "appdata", ".cache"}
MAX_SEEN, MAX_SECONDS = 60000, 4.0


class Refused(Exception):
    """A request that breaks a safety rule; the message is safe to say out loud."""


def expand(p):
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def roots(cfg_folders):
    """The allowed folders that actually exist (real, resolved paths)."""
    out = []
    for f in cfg_folders or []:
        try:
            p = expand(f).resolve()
            if p.is_dir() and p not in out:
                out.append(p)
        except (OSError, RuntimeError):
            pass
    return out


def inside(path, allowed):
    return any(path == r or r in path.parents for r in allowed)


def check_path(text, allowed, must_exist=True):
    """Turn what she was given into a real path inside an allowed folder, or raise Refused.
    Blocks network (UNC) paths, device names, '..' tricks and links that lead outside."""
    s = str(text or "").strip().strip('"')
    if not s:
        raise Refused("I need to know which file.")
    if s.startswith(("\\\\", "//")) or "\0" in s:
        raise Refused("I don't open network or device paths.")
    p = expand(s)
    if not p.is_absolute():
        if len(allowed) == 1:
            p = allowed[0] / p
        else:
            raise Refused("I need the full path of that file — I can find it for you first.")
    try:
        real = p.resolve()                      # follows links and '..' so an escape is seen for what it is
    except (OSError, RuntimeError):
        raise Refused("I couldn't read that path.")
    if not inside(real, allowed):
        raise Refused("That's outside the folders I'm allowed to use.")
    if must_exist and not real.exists():
        raise Refused("I can't find that.")
    return real


def check_openable(real):
    if real.is_file() and real.suffix.lower() in UNSAFE:
        raise Refused(f"I won't open {real.suffix} files — they can run programs. It is at {real}.")
    return real


def words(q):
    return [w for w in re.findall(r"[\w.\-]+", (q or "").lower()) if w not in ("the", "a", "my", "file", "files", "of")]


def find(query, allowed, limit=8):
    """Search file and folder NAMES (not contents) in the allowed folders. Newest first."""
    ws = words(query)
    if not ws:
        raise Refused("What should I look for?")
    hits, seen, t0 = [], 0, time.time()
    for root in allowed:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for name in files + dirs:
                seen += 1
                low = name.lower()
                if all(w in low for w in ws):
                    full = Path(dirpath) / name
                    try:
                        if inside(full.resolve(), allowed):            # a link out of the folder is not a hit
                            hits.append((full.stat().st_mtime, full))
                    except OSError:
                        pass
            if seen > MAX_SEEN or time.time() - t0 > MAX_SECONDS:
                break
        else:
            continue
        break
    hits.sort(key=lambda h: h[0], reverse=True)
    return [str(p) for _, p in hits[:limit]]
