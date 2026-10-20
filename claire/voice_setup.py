"""Voice setup: choose her voice in the Voice Studio, then test the microphone.
Run:  python -m claire.voice_setup"""
from . import config, voice_studio


def main():
    voice_studio.main()
    cfg = config.load()
    print("\n=== Microphone test (first run downloads the speech model, ~150 MB) ===")
    try:
        from .voice import Ears
        v = cfg["voice"]
        ears = Ears(v["stt_model"], v["language"], v["device"], v["mic"])
        print("Say something like “Hey Claire, what time is it?” …")
        text = ears.listen(max_wait=8, max_len=10)
        print(f"I heard: “{text}”" if text else "I didn't hear anything — check the microphone (use /mic in chat).")
    except ImportError as e:
        print(f"Not installed ({e.name}). Run setup_voice.bat again.")
    except Exception as e:
        print(f"Microphone/speech problem: {e}")
    print("\nDone. Start her with start_claire.bat.")


if __name__ == "__main__":
    main()
