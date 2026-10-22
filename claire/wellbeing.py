"""Break reminders. Watches what you're using — on this PC (the window in front) and on your phone (events you send) —
and tells you, kindly, when you've been at it too long. Only app NAMES and times are kept (today's totals), never content."""
import time

SUGGESTIONS = (
    "Stand up, stretch your back and shoulders, and look at something far away for twenty seconds.",
    "Drink some water and walk around for a few minutes.",
    "Rest your eyes: look out of a window and blink slowly a few times.",
    "Take five minutes away from the screen — your neck and eyes will thank you.",
)


def nice(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


class Usage:
    def __init__(self, same_app=90, continuous=120, gap=180, cooldown=1800, clock=time.time):
        self.same_app, self.continuous, self.gap, self.cooldown, self.clock = same_app, continuous, gap, cooldown, clock
        self.cur = None            # {"app", "start", "last"} — one app, no break longer than `gap`
        self.run_start = None      # when the current unbroken stretch of screen time began
        self.last_seen = None
        self.last_alert = 0.0
        self.today, self.day = {}, None
        self.n = 0

    def sample(self, app, idle_seconds=0.0, now=None):
        """Call every ~30 s with the app in front (None if unknown). Returns a break message or None."""
        now = self.clock() if now is None else now
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day != self.day:
            self.today, self.day = {}, day
        away = idle_seconds >= 300 or not app
        if self.last_seen is not None and (now - self.last_seen > self.gap or away):
            self.cur = self.run_start = None                       # you stepped away — that was a break
        dt = 0 if self.last_seen is None else min(now - self.last_seen, 120)
        self.last_seen = now
        if away:
            return None
        self.today[app] = self.today.get(app, 0) + dt
        if self.run_start is None:
            self.run_start = now
        if self.cur is None or self.cur["app"] != app:
            self.cur = {"app": app, "start": now}
        self.n += 1
        same_min, run_min = (now - self.cur["start"]) / 60, (now - self.run_start) / 60
        if now - self.last_alert < self.cooldown:
            return None
        tip = SUGGESTIONS[self.n // 7 % len(SUGGESTIONS)]
        if same_min >= self.same_app:
            self.last_alert = now
            return f"You've been in {pretty(app)} for {nice(same_min)} without a break. {tip}"
        if run_min >= self.continuous:
            self.last_alert = now
            return f"You've been on screens for {nice(run_min)} without a break. {tip}"
        return None

    def summary(self, top=6):
        if not self.today:
            return "I haven't tracked any screen time today yet."
        rows = sorted(self.today.items(), key=lambda kv: kv[1], reverse=True)[:top]
        total = sum(self.today.values()) / 60
        return f"Screen time today: {nice(total)} in all. " + "; ".join(f"{pretty(a)} {nice(s / 60)}" for a, s in rows) + "."


def pretty(app):
    a = str(app)
    for suffix in (".exe",):
        if a.lower().endswith(suffix):
            a = a[:-len(suffix)]
    return a[:1].upper() + a[1:] if a.islower() else a
