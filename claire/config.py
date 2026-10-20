"""Settings: settings.json next to the app, with safe defaults (nested sections merge)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "user_name": "Carl",
    "model": "qwen2.5:7b",
    "ollama_url": "http://localhost:11434",
    "temperature": 0.6,
    "context_tokens": 8192,
    "memories_per_turn": 6,
    "recent_turns_kept": 12,
    "auto_memory": True,
    "data_dir": "data",
    "ui": {"port": 8765, "open": True},    # Phase 3: her window
    "voice": {
        "enabled": True,
        "speak": "auto",
        "tts": "auto",                     # auto = kokoro → piper → windows · or: kokoro | edge | piper | windows
        "kokoro_model": "voices/kokoro-v1.0.onnx",
        "kokoro_voices": "voices/voices-v1.0.bin",
        "kokoro_voice": "af_heart",        # or a blend: "af_heart:0.7+bf_emma:0.3"
        "speed": 1.0,
        "edge_voice": "en-US-AvaMultilingualNeural",
        "edge_rate": "+0%",
        "edge_pitch": "+0Hz",
        "piper_voice": "voices/en_GB-jenny_dioco-medium.onnx",
        "stt_model": "base.en",
        "language": "en",
        "device": "cpu",
        "mic": None,
        "wake_engine": "whisper",
        "wake_words": ["claire", "clair", "clare", "clara", "klara", "claira"],
        "wake_model": "hey_jarvis",
        "wake_threshold": 0.5,
    },
}


def load(path=None):
    path = Path(path) if path else ROOT / "settings.json"
    cfg = json.loads(json.dumps(DEFAULTS))
    if path.exists():
        for k, v in json.loads(path.read_text(encoding="utf-8")).items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    d = Path(cfg["data_dir"])
    cfg["data_dir"] = str(d if d.is_absolute() else ROOT / d)
    Path(cfg["data_dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def save_setting(key, value, path=None):
    """key may be dotted: save_setting('voice.speak', 'on')."""
    path = Path(path) if path else ROOT / "settings.json"
    cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    node, parts = cur, key.split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value
    path.write_text(json.dumps(cur, indent=2), encoding="utf-8")


def identity_text():
    return (ROOT / "identity.md").read_text(encoding="utf-8")
