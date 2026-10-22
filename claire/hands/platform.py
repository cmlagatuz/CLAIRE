"""The only place that really touches the PC: opening things, starting programs, pressing volume keys.
Everything else in Phase 4 goes through this class, so tests swap it for a recording fake and nothing in the
tests ever opens a window or changes the volume."""
import os
import re
import shutil
import subprocess
import sys
import time

VK = {"mute": 0xAD, "down": 0xAE, "up": 0xAF}          # Windows media keys; each tap moves the volume by 2%
_QUIET = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


class Platform:
    windows = os.name == "nt"

    def open_path(self, target):
        """Open a file, folder, web address or system page with whatever program Windows (or the OS) picks for it."""
        if self.windows:
            os.startfile(target)                                    # noqa: S606 — only ever called with checked targets
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target], **_QUIET)
        else:
            subprocess.Popen(["xdg-open", target], **_QUIET)

    def launch(self, command):
        """Start a program from her app list: a system page (ms-settings:), a program on the PATH, a full path,
        or a name Windows knows (msedge, chrome, winword)."""
        if ":" in command and not re.match(r"^[A-Za-z]:[\\/]", command):
            return self.open_path(command)
        found = shutil.which(command) or (command if os.path.isabs(command) and os.path.exists(command) else None)
        if found:
            subprocess.Popen([found], **_QUIET)
        elif self.windows:
            done = subprocess.run(["cmd", "/c", "start", "", command], timeout=10, **_QUIET)
            if done.returncode != 0:
                raise FileNotFoundError(command)
        else:
            raise FileNotFoundError(command)

    def can_change_volume(self):
        return self.windows

    def volume_taps(self, key, count):
        """Press the volume-up / volume-down / mute key `count` times (Windows media keys)."""
        if not self.windows:
            raise NotImplementedError("volume keys are Windows only")
        import ctypes
        user32 = ctypes.windll.user32
        for _ in range(max(0, int(count))):
            user32.keybd_event(VK[key], 0, 0, 0)
            user32.keybd_event(VK[key], 0, 2, 0)                    # key up
            time.sleep(0.004)

    def list_processes(self):
        from . import procs
        return procs.read()

    def close_program(self, name):
        """Politely ask every process of this program to close (like clicking its X). Never forces it."""
        if self.windows:
            exe = name if name.lower().endswith(".exe") else name + ".exe"
            done = subprocess.run(["taskkill", "/IM", exe], timeout=20, capture_output=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            done = subprocess.run(["pkill", "-x", name], timeout=20, **{"capture_output": True})
        if done.returncode != 0:
            raise FileNotFoundError(name)

    # ---- Phase 4.7: network, phone, shortcuts ----------------------------------------------------
    def local_ip(self):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))                        # no packet is sent; it only picks the right adapter
            return s.getsockname()[0]
        finally:
            s.close()

    def arp_table(self, sweep_net=None):
        """Wake the devices on a /24 with one quick ping each, then read the ARP table."""
        from concurrent.futures import ThreadPoolExecutor
        if sweep_net is not None:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            cmd = (["ping", "-n", "1", "-w", "250"] if self.windows else ["ping", "-c", "1", "-W", "1"])

            def ping(ip):
                try:
                    subprocess.run(cmd + [str(ip)], capture_output=True, timeout=5, creationflags=flags)
                except Exception:
                    pass
            with ThreadPoolExecutor(48) as ex:
                list(ex.map(ping, sweep_net.hosts()))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["arp", "-a"] if self.windows else ["arp", "-an"], capture_output=True, text=True,
                             timeout=15, creationflags=flags)
        return out.stdout

    def device_name(self, ip):
        import socket
        try:
            return socket.gethostbyaddr(ip)[0].split(".")[0]
        except Exception:
            return ""

    def adb(self, args, adb_path="adb"):
        """Run one adb command (a fixed list of words — never a shell string)."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            done = subprocess.run([adb_path or "adb"] + list(args), capture_output=True, text=True, timeout=25,
                                  creationflags=flags)
        except FileNotFoundError:
            raise FileNotFoundError("adb")
        return done.returncode, (done.stdout + done.stderr).strip()

    def http_get(self, url):
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "CLAIRE"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.status
