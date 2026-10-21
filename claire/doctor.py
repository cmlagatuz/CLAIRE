"""Checks everything her voice and window need and says plainly what is missing.
Run:  python -m claire.doctor      (or double-click doctor.bat)"""
import importlib.util
import sys
from pathlib import Path

from . import config

SUPPORTED = ((3, 10), (3, 13))          # the Python versions the voice packages are known to install on
OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✓", WARN: "!", FAIL: "✗"}


def _has(module):
    """True if the module can be imported. (A separate function so tests can pretend something is missing.)"""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def python_note():
    v = sys.version_info
    where = "her own .venv" if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else "the system Python"
    return f"Python {v[0]}.{v[1]}.{v[2]} ({where}) at {sys.executable}"


def checks(cfg=None):
    """A list of (status, what, detail) — detail says what to do when something is not ok."""
    cfg = cfg or config.load()
    v = cfg["voice"]
    rows = []

    ver = sys.version_info[:2]
    if SUPPORTED[0] <= ver <= SUPPORTED[1]:
        rows.append((OK, "Python version", python_note()))
    else:
        rows.append((FAIL, "Python version", python_note() + f" — the voice packages are known to work on Python "
                     f"{SUPPORTED[0][0]}.{SUPPORTED[0][1]} to {SUPPORTED[1][0]}.{SUPPORTED[1][1]}. "
                     "Install Python 3.12, then run setup_claire.bat and setup_voice.bat (they give her her own copy)."))
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        rows.append((WARN, "Her own Python (.venv)", "not in use — run setup_claire.bat once so a different Python on this PC "
                     "can never break her voice."))
    else:
        rows.append((OK, "Her own Python (.venv)", "in use"))

    needs = [("numpy", "numpy", True), ("sounddevice", "sounddevice (microphone and speakers)", True),
             ("faster_whisper", "faster-whisper (her ears)", True), ("kokoro_onnx", "kokoro-onnx (her natural voice)", True),
             ("edge_tts", "edge-tts (optional online voices)", False)]
    for mod, label, required in needs:
        if _has(mod):
            rows.append((OK, label, "installed"))
        else:
            rows.append((FAIL if required else WARN, label,
                         "not installed — run setup_voice.bat and read any red error text it shows" if required
                         else "not installed (only needed for the online Edge voices)"))

    for key, label in (("kokoro_model", "Kokoro voice model"), ("kokoro_voices", "Kokoro voice list")):
        p = Path(v.get(key, ""))
        p = p if p.is_absolute() else config.ROOT / p
        if p.exists():
            rows.append((OK, label, f"{p.name} ({p.stat().st_size // 1024 // 1024} MB)"))
        else:
            rows.append((FAIL, label, f"{p} not found — run setup_voice.bat"))

    if _has("sounddevice"):
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            ins = [d for d in devs if d["max_input_channels"] > 0]
            outs = [d for d in devs if d["max_output_channels"] > 0]
            rows.append((OK if ins else FAIL, "Microphone", f"{len(ins)} found" if ins else "none found — plug one in, "
                         "or check Windows Settings → Privacy → Microphone"))
            rows.append((OK if outs else FAIL, "Speakers", f"{len(outs)} found" if outs else "none found"))
        except Exception as e:
            rows.append((WARN, "Audio devices", f"couldn't list them: {e}"))

    try:
        from .brain import Brain
        b = Brain(cfg["ollama_url"], cfg["model"])
        if b.online():
            have = b.models()
            rows.append((OK if cfg["model"] in have else WARN, "Brain (Ollama)",
                         f"running, model {cfg['model']} " + ("ready" if cfg["model"] in have
                                                              else f"not downloaded — run: ollama pull {cfg['model']}")))
        else:
            rows.append((FAIL, "Brain (Ollama)", "not running — start the Ollama app"))
    except Exception as e:
        rows.append((WARN, "Brain (Ollama)", f"couldn't check: {e}"))
    return rows


def report(rows):
    lines = [f" {MARK[s]}  {what:<42} {detail}" for s, what, detail in rows]
    bad = [r for r in rows if r[0] == FAIL]
    lines.append("")
    lines.append("Everything she needs is in place." if not bad else
                 f"{len(bad)} thing(s) need fixing. Start with the first ✗ above. If it isn't clear, send me this whole list.")
    return "\n".join(lines)


def main():
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("=== C.L.A.I.R.E. check ===\n")
    print(report(checks()))


if __name__ == "__main__":
    main()
