"""Live signals shared between her voice code and her window: what she is doing and how loud it is.
Written by voice.py (speaker loudness, microphone loudness) and web.py (activity); read by the window."""


class Signals:
    def __init__(self):
        self.activity = "idle"     # idle | listening | thinking | responding
        self.level = None          # loudness of her voice right now, 0..1 · None = unknown (e.g. mp3 playback)
        self.mic = 0.0             # loudness of the microphone, 0..1
        self.handsfree = False


signals = Signals()


def envelope(samples, rate, hop=0.03):
    """Relative loudness (0..1) of audio, one value per `hop` seconds. None if numpy isn't available."""
    try:
        import numpy as np
    except ImportError:
        return None
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    n = max(1, int(rate * hop))
    frames = len(x) // n
    if frames == 0:
        return [0.0]
    rms = np.sqrt(np.mean(x[:frames * n].reshape(frames, n) ** 2, axis=1))
    peak = float(np.percentile(rms, 95)) or 1e-6
    return [float(v) for v in np.clip(rms / peak, 0.0, 1.0) ** 0.8]


def mic_level(block):
    """Loudness of one microphone block as 0..1 (quiet room ≈ 0, normal speech ≈ 0.6–1)."""
    import numpy as np
    rms = float(np.sqrt(np.mean(np.asarray(block, dtype=np.float32) ** 2)))
    return min(1.0, (rms / 0.08) ** 0.6)
