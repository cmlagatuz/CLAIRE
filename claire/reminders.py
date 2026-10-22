"""Reminders (birthdays, appointments…) and quick notes. Plain files in data\\ — yours to read or delete."""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

REPEATS = ("none", "daily", "weekly", "monthly", "yearly")


class Refused(Exception):
    pass


def parse_when(text, now=None, default_hour=9):
    """'2027-03-14' (→ 09:00) or '2027-03-14T17:30' → a datetime."""
    now = now or datetime.now()
    s = str(text or "").strip().replace(" ", "T", 1) if " " in str(text or "").strip()[:11] else str(text or "").strip()
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise Refused("I need the date as YYYY-MM-DD (and optionally the time as YYYY-MM-DDTHH:MM).")
    if "T" not in s and len(s) <= 10:
        d = d.replace(hour=default_hour, minute=0)
    return d.replace(tzinfo=None, second=0, microsecond=0)


def advance(d, repeat):
    if repeat == "daily":
        return d + timedelta(days=1)
    if repeat == "weekly":
        return d + timedelta(days=7)
    if repeat == "monthly":
        y, m = (d.year + (d.month // 12), d.month % 12 + 1)
        for day in range(d.day, 27, -1):
            try:
                return d.replace(year=y, month=m, day=day)
            except ValueError:
                continue
        return d.replace(year=y, month=m, day=min(d.day, 28))
    if repeat == "yearly":
        try:
            return d.replace(year=d.year + 1)
        except ValueError:                                  # 29 February
            return d.replace(year=d.year + 1, day=28)
    return None


class Reminders:
    def __init__(self, data_dir, clock=datetime.now):
        self.path = Path(data_dir) / "reminders.json"
        self.notes = Path(data_dir) / "notes.jsonl"
        self.clock, self.lock = clock, threading.Lock()

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, items):
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, text, when, repeat="none"):
        text = str(text or "").strip()[:200]
        repeat = str(repeat or "none").lower()
        if not text:
            raise Refused("What should I remind you about?")
        if repeat not in REPEATS:
            raise Refused("Repeat can be none, daily, weekly, monthly or yearly.")
        now = self.clock()
        due = parse_when(when, now)
        if due < now:
            if repeat == "none":
                raise Refused(f"{due:%d %B %Y %H:%M} is already in the past. What date did you mean?")
            while due < now:
                due = advance(due, repeat)
        with self.lock:
            items = self._load()
            item = {"id": max([i["id"] for i in items], default=0) + 1, "text": text, "due": due.isoformat(timespec="minutes"),
                    "repeat": repeat}
            items.append(item)
            self._save(items)
        return item

    def upcoming(self, days=60):
        now = self.clock()
        out = [i for i in self._load() if datetime.fromisoformat(i["due"]) <= now + timedelta(days=days)]
        return sorted(out, key=lambda i: i["due"])

    def due(self):
        """Reminders whose time has come. One-off ones are removed; repeating ones move to their next date."""
        now, fired = self.clock(), []
        with self.lock:
            items, keep = self._load(), []
            for i in items:
                d = datetime.fromisoformat(i["due"])
                if d <= now:
                    fired.append(i)
                    nxt = advance(d, i["repeat"])
                    while nxt and nxt <= now:
                        nxt = advance(nxt, i["repeat"])
                    if nxt:
                        keep.append(dict(i, due=nxt.isoformat(timespec="minutes")))
                else:
                    keep.append(i)
            if fired:
                self._save(keep)
        return fired

    def remove(self, rid):
        with self.lock:
            items = self._load()
            keep = [i for i in items if i["id"] != rid]
            self._save(keep)
        return len(keep) != len(items)

    def today(self):
        now = self.clock()
        return [i for i in self._load() if datetime.fromisoformat(i["due"]).date() == now.date()]

    # ---- notes ----
    def note(self, text):
        text = str(text or "").strip()[:2000]
        if not text:
            raise Refused("What should I write down?")
        with self.lock, open(self.notes, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": self.clock().isoformat(timespec="minutes"), "text": text}, ensure_ascii=False) + "\n")
        return text

    def recent_notes(self, n=10, query=""):
        try:
            rows = [json.loads(x) for x in self.notes.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, ValueError):
            return []
        q = str(query or "").lower().split()
        if q:
            rows = [r for r in rows if all(w in r["text"].lower() for w in q)]
        return rows[-n:][::-1]
