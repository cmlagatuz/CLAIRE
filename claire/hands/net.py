"""Your own network, read-only: which devices are on this Wi-Fi, and is there one you haven't seen before?
She never connects to, controls or disconnects any of them. Private (home) address ranges only."""
import ipaddress
import json
import re
from pathlib import Path

from .files import Refused

MAC = re.compile(r"\b([0-9a-f]{2}(?:[-:][0-9a-f]{2}){5})\b", re.I)
IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


HOME = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def is_private(ip):
    """Only the three ranges home routers hand out (RFC 1918). Not loopback, link-local, documentation or public."""
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    return a.version == 4 and any(a in n for n in HOME)


def lan(ip):
    """The /24 around an address — and only if it is a home-style private address."""
    if not is_private(ip):
        raise Refused("This doesn't look like a home network, so I won't scan it.")
    return ipaddress.ip_network(f"{ip}/24", strict=False)


def parse_arp(text):
    """`arp -a` (Windows) or `arp -an` (Linux/Mac) → [{ip, mac}], without broadcast/multicast noise."""
    out, seen = [], set()
    for line in str(text).splitlines():
        ip, mac = IP.search(line), MAC.search(line)
        if not ip or not mac or not is_private(ip.group(1)):
            continue
        m = mac.group(1).lower().replace("-", ":")
        if m in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") or m.startswith("01:00:5e") or ip.group(1).endswith(".255"):
            continue
        if ip.group(1) not in seen:
            seen.add(ip.group(1))
            out.append({"ip": ip.group(1), "mac": m})
    return sorted(out, key=lambda d: tuple(int(x) for x in d["ip"].split(".")))


class Known:
    """The devices Carl has said he recognises (data/network_known.json)."""
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "network_known.json"

    def macs(self):
        try:
            return set(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    def trust(self, macs):
        self.path.write_text(json.dumps(sorted(self.macs() | set(macs))), encoding="utf-8")


def describe(devices, known, me=None):
    if not devices:
        return "I couldn't see any other devices on this network."
    new = [d for d in devices if d["mac"] not in known] if known else []
    lines = [f"{len(devices)} devices on your network" + (f" (this PC is {me})" if me else "") + "."]
    if not known:
        lines.append("I don't know yet which of these are yours — say \"trust these devices\" once you've checked them, and I'll warn you about new ones after that.")
    elif new:
        lines.append(f"{len(new)} I haven't seen before: " + "; ".join(label(d) for d in new[:8]) + ". If you don't recognise them, check your router.")
    else:
        lines.append("All of them are devices you've already told me about.")
    lines.append("List: " + "; ".join(label(d) for d in devices[:30]))
    return "\n".join(lines)


def label(d):
    return f"{d['ip']} {d.get('name') or ''} ({d['mac']})".replace("  ", " ")
