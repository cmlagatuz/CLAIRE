"""What is running — the same picture as Task Manager, grouped by program. Read-only, standard library only.
Also the list of programs she must never close."""
import os
import re
import subprocess

# Windows' own parts, security software, and the pieces she herself needs (her brain, her Python).
PROTECTED = {
    "system", "system idle process", "registry", "memory compression", "secure system", "smss", "csrss", "wininit",
    "services", "lsass", "lsm", "svchost", "winlogon", "explorer", "dwm", "fontdrvhost", "sihost", "taskhostw",
    "ctfmon", "conhost", "dllhost", "audiodg", "spoolsv", "wudfhost", "searchhost", "searchindexer", "runtimebroker",
    "startmenuexperiencehost", "shellexperiencehost", "textinputhost", "securityhealthservice",
    "securityhealthsystray", "msmpeng", "nissrv", "smartscreen", "vmmem", "vmcompute", "wslservice", "wsl",
    "windowsterminal", "cmd", "powershell", "pwsh", "python", "pythonw", "py", "ollama", "ollama app",
    "ollama_llama_server", "ollama-runner", "claire",
    # Linux / macOS equivalents so the same rule holds anywhere she is developed
    "systemd", "init", "kthreadd", "bash", "sh", "zsh", "sshd", "dbus-daemon", "login", "launchd", "kernel_task",
}
NAME_OK = re.compile(r"^[\w][\w .+\-]{0,63}$")


def key(name):
    n = str(name or "").strip().lower()
    return n[:-4] if n.endswith(".exe") else n


def protected(name):
    k = key(name)
    return k in PROTECTED or k.startswith(("python", "ollama", "systemd", "kworker")) or k.endswith("-claire")


def read():
    """[{name, pid, mb}] for every process (best effort; [] if it can't be read)."""
    try:
        return _windows() if os.name == "nt" else _linux()
    except Exception:
        return []


def _windows():
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=20,
                         creationflags=flags).stdout
    import csv
    rows = []
    for r in csv.reader(out.splitlines()):
        if len(r) >= 5:
            digits = re.sub(r"\D", "", r[4])
            if digits and r[1].isdigit():
                rows.append({"name": r[0], "pid": int(r[1]), "mb": int(digits) / 1024.0})   # tasklist reports KB
    return rows


def _linux():
    rows, page = [], os.sysconf("SC_PAGE_SIZE")
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open(f"/proc/{pid}/comm") as f:
                    name = f.read().strip()
                with open(f"/proc/{pid}/statm") as f:
                    rss = int(f.read().split()[1])
                rows.append({"name": name, "pid": int(pid), "mb": rss * page / 1048576.0})
            except (OSError, ValueError, IndexError):
                pass
    return rows


def group(rows):
    """One line per program: {name, count, mb, protected}, biggest first."""
    g = {}
    for r in rows:
        k = key(r["name"])
        e = g.setdefault(k, {"name": r["name"], "count": 0, "mb": 0.0, "protected": protected(r["name"])})
        e["count"] += 1
        e["mb"] += r["mb"]
    return sorted(g.values(), key=lambda e: e["mb"], reverse=True)


def size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def describe(groups, count=5):
    if not groups:
        return "I couldn't read the list of running programs."
    parts = []
    for e in groups[:max(1, min(int(count), 12))]:
        many = f" ({e['count']} processes)" if e["count"] > 1 else ""
        parts.append(f"{key(e['name']).title()} {size(e['mb'])}{many}{' (system, off limits)' if e['protected'] else ''}")
    return "Using the most memory right now: " + "; ".join(parts) + "."


def closable(groups, min_mb=300):
    """Biggest program that is safe to suggest closing, or None."""
    for e in groups:
        if not e["protected"] and e["mb"] >= min_mb:
            return e
    return None


BROWSERS = ("chrome", "msedge", "edge", "firefox", "brave", "opera", "vivaldi")


def resolve(groups, wanted):
    """The running program(s) the user most likely means: exact name, else a part of a name ("chrome" → "chrome.exe"),
    else "browser" → the biggest browser that is running."""
    w = key(wanted)
    if not w:
        return []
    exact = [e for e in groups if key(e["name"]) == w]
    if exact:
        return exact
    if w in ("browser", "web browser", "my browser", "the browser"):
        b = [e for e in groups if key(e["name"]) in BROWSERS]
        return b[:1]
    part = [e for e in groups if len(w) >= 3 and w in key(e["name"])]
    return part[:1] if len({key(e["name"]) for e in part}) == 1 else []
