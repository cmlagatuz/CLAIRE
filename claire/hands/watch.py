"""Keeps an eye on memory the way you watch Task Manager. When RAM runs high she speaks up once (not nagging),
names the heavy programs, and asks whether to close the biggest one she is allowed to touch."""
import threading
import time

from . import procs, sysinfo


class RamWatch:
    def __init__(self, hands, say, warn_at=85, every=30, quiet_for=900, clock=time.time, reader=sysinfo.read):
        self.hands, self.say = hands, say
        self.warn_at, self.every, self.quiet_for = warn_at, every, quiet_for
        self.clock, self.reader = clock, reader
        self.last, self.stop_ev = None, threading.Event()

    def check(self):
        """One look. Returns the warning she said, or None."""
        d = self.reader()
        if not d.get("mem_total"):
            return None
        pct = 100.0 * (d["mem_total"] - d["mem_free"]) / d["mem_total"]
        now = self.clock()
        if pct < self.warn_at or (self.last is not None and now - self.last < self.quiet_for):
            return None
        self.last = now
        groups = procs.group(self.hands.platform.list_processes())
        text = f"Memory is at {pct:.0f}%. " + procs.describe(groups, 3)
        pick = procs.closable(groups)
        if pick and self.hands.enabled:
            res = self.hands.call("close_program", {"name": pick["name"]})
            if res["status"] == "pending":
                text += f" Want me to close {procs.key(pick['name']).title()}? It's the biggest one I'm allowed to close."
            elif res["status"] == "done":
                text += f" {res['text']}"                   # one Carl put on his own auto-close list
        self.hands.log("warned", "ram_watch", {"percent": round(pct)}, text)
        self.say(text)
        return text

    def start(self):
        def loop():
            while not self.stop_ev.wait(self.every):
                try:
                    self.check()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.stop_ev.set()
