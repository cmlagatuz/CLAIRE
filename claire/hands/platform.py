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
