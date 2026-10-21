"""Phase 3.2 · a global hotkey and a tray icon for her window.

Hotkey  — Windows only, nothing to install (uses the system's RegisterHotKey). Default Ctrl+Alt+C:
          press it anywhere and she starts listening (and her window opens if it was closed).
Tray    — optional: pip install pystray pillow. Gives her a little icon with Open / Talk / Quit.
Both fail softly: if one can't start, she says why in the console and everything else keeps working."""
import sys
import threading

MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
NOREPEAT = 0x4000
KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B}
KEYS.update({f"f{i}": 0x6F + i for i in range(1, 13)})
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012


def parse_hotkey(text):
    """'ctrl+alt+c' → (modifier bits, virtual-key code). Raises ValueError for anything unusable."""
    parts = [p.strip().lower() for p in str(text).replace(" ", "").split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("a hotkey needs a modifier and a key, like ctrl+alt+c")
    *mods, key = parts
    bits = 0
    for m in mods:
        if m not in MODS:
            raise ValueError(f"unknown modifier '{m}' (use ctrl, alt, shift or win)")
        bits |= MODS[m]
    if not bits & (MODS["ctrl"] | MODS["alt"] | MODS["win"]):
        raise ValueError("use at least ctrl, alt or win so typing isn't affected")
    if key in KEYS:
        return bits, KEYS[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return bits, ord(key.upper())
    raise ValueError(f"unknown key '{key}'")


class Hotkey:
    """Runs its own message loop in a thread; calls `callback()` on every press."""

    def __init__(self, combo, callback):
        self.combo, self.callback = combo, callback
        self.mods, self.vk = parse_hotkey(combo)
        self.thread_id, self.error = None, None
        self._ready = threading.Event()

    def start(self):
        if not sys.platform.startswith("win"):
            raise RuntimeError("global hotkeys work on Windows only")
        threading.Thread(target=self._loop, daemon=True).start()
        self._ready.wait(3)
        if self.error:
            raise RuntimeError(self.error)

    def _loop(self):
        import ctypes
        from ctypes import wintypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        self.thread_id = k.GetCurrentThreadId()
        if not u.RegisterHotKey(None, 1, self.mods | NOREPEAT, self.vk):
            self.error = f"{self.combo} is already used by another program"
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        pass
        finally:
            u.UnregisterHotKey(None, 1)

    def stop(self):
        if self.thread_id and sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def start_tray(on_open, on_talk, on_quit):
    """Returns the tray icon, or None (with a reason) if pystray/pillow aren't installed."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None, "tray icon needs:  pip install pystray pillow   (optional)"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(32, 32), (14, 20), (50, 18), (46, 48), (16, 46), (32, 8), (56, 34), (8, 34)]
    for p in pts[1:]:
        d.line([pts[0], p], fill=(143, 168, 255, 200), width=2)
    for i, p in enumerate(pts):
        c = [(245, 160, 58), (91, 143, 209), (95, 196, 176), (236, 143, 180), (247, 213, 72), (229, 89, 91),
             (91, 178, 77), (212, 212, 218)][i % 8]
        r = 7 if i == 0 else 4
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=c + (255,))
    menu = pystray.Menu(pystray.MenuItem("Open Claire", lambda *_: on_open(), default=True),
                        pystray.MenuItem("Talk to Claire", lambda *_: on_talk()),
                        pystray.MenuItem("Quit", lambda *_: on_quit()))
    icon = pystray.Icon("claire", img, "C.L.A.I.R.E.", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon, ""
