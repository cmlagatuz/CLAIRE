"""Makes the pictures in README.md from the real window (headless Chromium) with fake voice/brain/PC,
so nothing is opened, spoken or changed.   Run:  python docs/make_screenshots.py   (needs: pip install playwright)"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from claire import config, web                                      # noqa: E402
from claire.signals import signals                                  # noqa: E402
from test_phase3 import make_session                                # noqa: E402
from test_phase4 import setup_hands                                 # noqa: E402
from playwright.sync_api import sync_playwright                     # noqa: E402

OUT = ROOT / "docs" / "images"
config.save_setting = lambda *a, **k: None                          # never touch the real settings.json


def build():
    s, app = make_session()
    h, pc, docs = setup_hands()
    (docs / "Visa report - Q3.pdf").write_text("x")
    (docs / "Visa tracker.xlsx").write_text("x")
    s.hands = app.c.hands = h
    h.on_change = lambda: s.hub.publish("pending", items=h.pending())
    c = app.c
    for t in ("Carl is building me, C.L.A.I.R.E., on his own PC",):
        c.store.remember(t, "core", "manual")
    c.store.remember("Carl prefers short answers", "fact", "auto")
    c.store.remember("Carl works on visa and recruitment records", "fact", "auto")
    # a believable day of actions
    h.call("system_status", {"topic": "all"})
    h.call("find_files", {"query": "visa"})
    h.call("open_app", {"name": "calculator"}); h.answer("yes")
    h.call("open_file", {"path": str(docs / "Visa report - Q3.pdf")}); h.answer("yes")
    h.call("open_website", {"url": "https://example.com"}); h.answer("no")
    h.call("open_app", {"name": "powershell"})
    h.call("open_file", {"path": "C:\\Windows\\System32\\cmd.exe"})
    return s, app, h


def say(pg, user, answer):
    pg.evaluate("""([u, a]) => { const y = document.getElementById('you'), n = document.getElementById('answer'),
        c = document.getElementById('caption'); y.textContent = u; n.textContent = a; c.classList.remove('fade'); }""",
                [user, answer])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s, app, h = build()
    srv = web.Server(s, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("dark", "light"):
            pg = b.new_page(viewport={"width": 1100, "height": 760}, color_scheme=scheme)
            pg.goto(srv.url)
            time.sleep(0.9)
            if scheme == "dark":
                for state, user, ans in (("idle", "", ""), ("listening", "", ""),
                                         ("thinking", "What's on my calendar tomorrow?", ""),
                                         ("speaking", "How's my PC doing?",
                                          "The processor is at 7%. Memory: 5.1 GB of 16 GB in use. Disk D: has 120 GB free.")):
                    signals.activity = {"speaking": "responding"}.get(state, state)
                    signals.level = 0.55 if state == "speaking" else 0.0
                    signals.mic = 0.5 if state == "listening" else 0.0
                    say(pg, user, ans)
                    time.sleep(1.1)
                    pg.screenshot(path=str(OUT / f"orb_{state}.png"))
                signals.activity, signals.level, signals.mic = "idle", 0.0, 0.0
                # Phase 4: she asks first
                say(pg, "Open notepad", "")
                h.call("open_app", {"name": "notepad"})
                time.sleep(0.8)
                pg.screenshot(path=str(OUT / "hands_ask.png"))
                pg.click("#askYes")
                time.sleep(0.8)
                pg.screenshot(path=str(OUT / "hands_done.png"))
                pg.click("#memBtn"); time.sleep(0.6)
                pg.screenshot(path=str(OUT / "panel_memories.png"))
                pg.click("#tabJour"); time.sleep(0.6)
                pg.screenshot(path=str(OUT / "panel_journal.png"))
                pg.click("#tabVoice"); time.sleep(0.8)
                pg.screenshot(path=str(OUT / "panel_voice.png"))
                pg.click("#tabHands"); time.sleep(0.8)
                pg.screenshot(path=str(OUT / "panel_actions.png"))
            else:
                signals.activity = "responding"
                signals.level = 0.5
                say(pg, "Find my visa report", "I found two files. Say “open the first one” and I'll ask before opening it.")
                time.sleep(1.1)
                pg.screenshot(path=str(OUT / "orb_light.png"))
                signals.activity, signals.level = "idle", 0.0
                pg.click("#memBtn"); pg.click("#tabHands"); time.sleep(0.8)
                pg.screenshot(path=str(OUT / "panel_actions_light.png"))
            pg.close()
        b.close()
    srv.stopping = True
    print("wrote", sorted(x.name for x in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
