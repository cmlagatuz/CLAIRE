"""Health watching — a careful ALERT layer, not a doctor.
She can notice readings from your watch that look abnormal and tell you to get help. She cannot diagnose anything,
no watch can reliably detect a heart attack, and silence from her never means you are fine."""
import re
import time
from collections import deque

EMERGENCY_NUMBER = "997 for an ambulance in Saudi Arabia (911 also works)"

# Said by YOU, in words: this is checked before anything else, locally, with no AI and no tools in between.
EMERGENCY = re.compile(
    r"\b(chest (?:pain|pressure|tightness|hurts?|is (?:tight|crushing))|pain in my (?:chest|left arm|arm|jaw)|"
    r"(?:having|think i(?:'m| am) having|might be having) a (?:heart attack|stroke)|"
    r"(?:can'?t|cannot|can not|struggling to|hard to) breathe|short(?:ness)? of breath|crushing (?:pain|feeling)|"
    r"i(?:'m| am) (?:going to |about to )?(?:faint|pass(?:ing)? out|collaps\w+)|(?:face|arm) (?:is )?(?:drooping|numb)|"
    r"slurred speech|call (?:an )?ambulance|i(?:'m| am) not (?:ok|okay|alright))\b", re.I)
SILENT_PART = " If you say nothing, I'll make the call myself in under a minute."
EMERGENCY_REPLY = (f"This could be serious. Calling your local emergency number is what you need now — {EMERGENCY_NUMBER}. "
                   "Say yes and I'll call it for you right now, or say stop to cancel." + SILENT_PART +
                   " Sit down, unlock your door, and tell anyone near you. I'm not a doctor and I can't judge this from here.")
FINE = re.compile(r"^\W*(i(?:'m| am)? (?:fine|ok|okay|alright|good)|(?:all )?(?:fine|ok|okay)|false alarm|"
                  r"just (?:exercising|working out|walking|running)|i(?:'m| am) exercising)\b", re.I)


class Alert:
    def __init__(self, key, level, text):
        self.key, self.level, self.text = key, level, text

    def __repr__(self):
        return f"Alert({self.key},{self.level})"


class Vitals:
    """What the watch has told her recently (kept 30 days, only on this PC)."""
    def __init__(self, clock=time.time, keep=30 * 86400):
        self.clock, self.keep = clock, keep
        self.d = {"hr": deque(maxlen=5000), "spo2": deque(maxlen=2000), "steps": deque(maxlen=5000)}

    def add(self, kind, value, t=None):
        t = self.clock() if t is None else t
        self.d[kind].append((t, float(value)))
        while self.d[kind] and t - self.d[kind][0][0] > self.keep:
            self.d[kind].popleft()

    def recent(self, kind, seconds, now=None):
        now = self.clock() if now is None else now
        return [(t, v) for t, v in self.d[kind] if now - t <= seconds]

    def last(self, kind):
        return self.d[kind][-1] if self.d[kind] else None

    def moving(self, now=None, minutes=10):
        """Steps in the last few minutes (None when the watch hasn't reported steps at all)."""
        if not self.d["steps"]:
            return None
        return sum(v for _, v in self.recent("steps", minutes * 60, now))

    def status(self, now=None):
        now = self.clock() if now is None else now
        out, parts = {}, []
        for kind, label, unit in (("hr", "Heart rate", " bpm"), ("spo2", "Blood oxygen", "%")):
            last = self.last(kind)
            if last:
                age = (now - last[0]) / 60
                out[kind] = (last[1], age)
                parts.append(f"{label} {last[1]:.0f}{unit} ({age_text(age)})")
        if not parts:
            return "I haven't received any readings from your watch, so I can't tell you anything about your health right now."
        stale = all(a > 15 for _, a in out.values())
        txt = "Latest from your watch: " + "; ".join(parts) + "."
        if stale:
            txt += " These are old, so they say nothing about how you are right now."
        return txt + " I'm not a doctor — if you feel unwell, trust that over any number."


def age_text(minutes):
    if minutes < 1:
        return "just now"
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    return f"{minutes / 60:.1f} h ago"


def assess(v, now=None):
    """Alerts for the current readings. Deliberately conservative about WORDING (never reassures) and
    moderate about thresholds (a resting 120+ for minutes, SpO2 ≤ 90, HR ≤ 40)."""
    now = v.clock() if now is None else now
    out = []
    hr15 = v.recent("hr", 15 * 60, now)
    moving = v.moving(now)
    idle = moving is None or moving < 40
    if len(hr15) >= 3 and all(x >= 120 for _, x in hr15[-3:]) and idle:
        out.append(Alert("hr_high", "check", f"Your heart rate has been {hr15[-1][1]:.0f} for several minutes and I don't see you moving."))
    if hr15 and hr15[-1][1] >= 160 and idle:
        out.append(Alert("hr_very_high", "urgent", f"Your heart rate just read {hr15[-1][1]:.0f} while you seem to be resting."))
    low = v.recent("hr", 10 * 60, now)
    if len(low) >= 2 and all(x <= 40 for _, x in low[-2:]):
        out.append(Alert("hr_low", "check", f"Your heart rate has read {low[-1][1]:.0f} twice in a row, which is very low."))
    ox = v.recent("spo2", 15 * 60, now)
    if ox and ox[-1][1] <= 85:
        out.append(Alert("spo2_critical", "urgent", f"Your blood oxygen read {ox[-1][1]:.0f}%, which is dangerously low."))
    elif len(ox) >= 2 and all(x <= 90 for _, x in ox[-2:]):
        out.append(Alert("spo2_low", "check", f"Your blood oxygen has read {ox[-1][1]:.0f}% twice in a row."))
    return out


class Monitor:
    """Turns assessments into at most a few spoken alerts. Urgent ones repeat (every 5 minutes) until you answer."""
    CHECK_QUIET, URGENT_QUIET, FINE_QUIET = 3600, 300, 3600

    def __init__(self, vitals, say, clock=time.time):
        self.v, self.say, self.clock = vitals, say, clock
        self.last, self.fine_until, self.awaiting = {}, {}, None

    def check(self):
        now, said = self.clock(), []
        for a in assess(self.v, now):
            if now < self.fine_until.get(a.key, 0):
                continue
            quiet = self.URGENT_QUIET if a.level == "urgent" else self.CHECK_QUIET
            if now - self.last.get(a.key, 0) < quiet:
                continue
            self.last[a.key] = now
            if a.level == "urgent":
                text = f"{a.text} {EMERGENCY_REPLY}"
            else:
                text = f"{a.text} Are you okay? Tell me \"I'm fine\" or \"I'm not okay\". I'm not a doctor, and if you feel unwell, get help."
                self.awaiting = a.key
            self.say(text, urgent=a.level == "urgent")
            said.append(a)
        return said

    def reply(self, text):
        """Carl answered a check-in. Returns what to say, or None when he was talking about something else."""
        if EMERGENCY.search(text):
            return EMERGENCY_REPLY
        if self.awaiting and FINE.match(text):
            self.fine_until[self.awaiting] = self.clock() + self.FINE_QUIET
            self.awaiting = None
            return "Okay, I'm glad. I'll check again if the numbers stay like that, and I won't mention it for an hour."
        return None
