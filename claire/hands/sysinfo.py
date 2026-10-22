"""How the PC is doing — CPU, memory, disks, battery, uptime. Read-only, standard library only
(Windows system calls through ctypes; /proc on Linux so it can be developed and tested anywhere)."""
import os
import shutil
import time

TOPICS = ("all", "cpu", "memory", "disk", "battery", "uptime")


def _gb(n):
    n = float(n)
    return f"{n / 1024 ** 4:.1f} TB" if n >= 1000 * 1024 ** 3 else f"{n / 1024 ** 3:.1f} GB"


def _span(seconds):
    m = int(seconds // 60)
    d, m = divmod(m, 1440)
    h, m = divmod(m, 60)
    parts = [f"{d} day{'s' if d != 1 else ''}"] if d else []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m and not d:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    return " ".join(parts) or "under a minute"


def read():
    """A dict with whatever could be measured: cpu (%), mem_total/mem_free (bytes), disks, battery, uptime (s)."""
    try:
        return _windows() if os.name == "nt" else _linux()
    except Exception:
        return {}


def _windows():
    import ctypes
    k = ctypes.windll.kernel32
    d = {}

    class MemStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class Power(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    class FileTime(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]

    m = MemStatus()
    m.dwLength = ctypes.sizeof(MemStatus)
    if k.GlobalMemoryStatusEx(ctypes.byref(m)):
        d["mem_total"], d["mem_free"] = m.ullTotalPhys, m.ullAvailPhys
    p = Power()
    if k.GetSystemPowerStatus(ctypes.byref(p)) and p.BatteryFlag != 128 and p.BatteryLifePercent <= 100:
        d["battery"] = {"percent": int(p.BatteryLifePercent), "plugged": p.ACLineStatus == 1}
    k.GetTickCount64.restype = ctypes.c_ulonglong
    d["uptime"] = k.GetTickCount64() / 1000.0

    def times():
        idle, kern, user = FileTime(), FileTime(), FileTime()
        k.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        return [(x.hi << 32) | x.lo for x in (idle, kern, user)]
    a = times()
    time.sleep(0.3)
    b = times()
    busy = (b[1] - a[1]) + (b[2] - a[2])                    # kernel time includes idle time
    if busy > 0:
        d["cpu"] = max(0.0, min(100.0, 100.0 * (1 - (b[0] - a[0]) / busy)))
    disks = []
    mask = k.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if k.GetDriveTypeW(root) in (2, 3):             # removable or fixed, not network / CD
                try:
                    u = shutil.disk_usage(root)
                    disks.append({"name": root[:2], "total": u.total, "free": u.free})
                except OSError:
                    pass
    d["disks"] = disks
    return d


def _linux():
    d = {}
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            mem[key] = int(rest.split()[0]) * 1024
    d["mem_total"], d["mem_free"] = mem["MemTotal"], mem.get("MemAvailable", mem.get("MemFree", 0))
    with open("/proc/uptime") as f:
        d["uptime"] = float(f.read().split()[0])

    def cpu():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        return v[3] + (v[4] if len(v) > 4 else 0), sum(v)
    (i1, t1), _ = cpu(), time.sleep(0.3)
    i2, t2 = cpu()
    if t2 > t1:
        d["cpu"] = 100.0 * (1 - (i2 - i1) / (t2 - t1))
    disks = []
    for name, path in (("/", "/"), ("home", os.path.expanduser("~"))):
        try:
            u = shutil.disk_usage(path)
            if not any(x["total"] == u.total and x["free"] == u.free for x in disks):
                disks.append({"name": name, "total": u.total, "free": u.free})
        except OSError:
            pass
    d["disks"] = disks
    try:
        base = "/sys/class/power_supply"
        for n in sorted(os.listdir(base)):
            if n.startswith("BAT"):
                with open(f"{base}/{n}/capacity") as f:
                    pct = int(f.read())
                with open(f"{base}/{n}/status") as f:
                    st = f.read().strip().lower()
                d["battery"] = {"percent": pct, "plugged": st in ("charging", "full")}
                break
    except OSError:
        pass
    return d


def describe(d, topic="all"):
    """The answer in plain sentences, ready to be read aloud."""
    topic = topic if topic in TOPICS else "all"
    parts = {}
    if "cpu" in d:
        parts["cpu"] = f"The processor is at {d['cpu']:.0f}%."
    if "mem_total" in d:
        used = d["mem_total"] - d["mem_free"]
        parts["memory"] = f"Memory: {_gb(used)} of {_gb(d['mem_total'])} in use ({100 * used / d['mem_total']:.0f}%)."
    if d.get("disks"):
        parts["disk"] = "Disk space: " + "; ".join(
            f"{x['name']} has {_gb(x['free'])} free of {_gb(x['total'])}" for x in d["disks"]) + "."
    if "battery" in d:
        b = d["battery"]
        parts["battery"] = f"Battery is at {b['percent']}% and {'charging or plugged in' if b['plugged'] else 'running on battery'}."
    elif topic == "battery":
        parts["battery"] = "I don't see a battery, so this looks like a desktop PC."
    if "uptime" in d:
        parts["uptime"] = f"It has been on for {_span(d['uptime'])}."
    if topic != "all":
        return parts.get(topic) or f"I couldn't read the {topic} on this PC."
    return " ".join(parts[k] for k in ("cpu", "memory", "disk", "battery", "uptime") if k in parts) or \
        "I couldn't read anything about this PC."
