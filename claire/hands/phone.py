"""Your Android phone through ADB over Wi-Fi (Samsung included). Needs Android 'platform-tools' (adb) on this PC and
'Wireless debugging' switched on in the phone's Developer options. Everything here is checked before it runs."""
import re

from .files import Refused
from .net import is_private

ADDR = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})$")
PACKAGE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", re.I)


def check_address(text):
    m = ADDR.match(str(text or "").strip())
    if not m or not is_private(m.group(1)) or not 1 <= int(m.group(2)) <= 65535:
        raise Refused("I need the phone's address on your Wi-Fi, like 192.168.1.20:5555 (shown in Wireless debugging).")
    return f"{m.group(1)}:{m.group(2)}"


def parse_devices(text):
    """`adb devices` → [(serial, state)]"""
    out = []
    for line in str(text).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def parse_battery(text):
    d = {}
    for line in str(text).splitlines():
        k, _, v = line.strip().partition(":")
        d[k.strip().lower()] = v.strip()
    try:
        level, scale = int(d["level"]), int(d.get("scale") or 100)
    except (KeyError, ValueError):
        return None
    status = {"2": "charging", "3": "discharging", "4": "not charging", "5": "full"}.get(d.get("status", ""), "unknown")
    return {"percent": round(100 * level / scale), "state": status}


def check_app(name, apps):
    key = str(name or "").strip().lower()
    apps = {k.lower(): v for k, v in (apps or {}).items()}
    if key not in apps:
        known = ", ".join(sorted(apps)) or "none"
        raise Refused(f"I only open phone apps on my list. I can open: {known}.")
    if not PACKAGE.match(apps[key]):
        raise Refused("That app's package name in my settings doesn't look right.")
    return key, apps[key]
