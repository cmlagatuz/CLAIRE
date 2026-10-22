"""Phase 4 · Hands — tools on the PC. See tools.Hands."""
from .tools import Hands, SPECS          # noqa: F401


def attach(claire, save=None):
    """Give a Claire her hands (when switched on in settings). `save(key, value)` stores 'always' choices."""
    from .tools import Hands as H
    if not claire.cfg.get("tools", {}).get("enabled", True):
        return None
    h = H(claire.cfg)
    h.persist = save
    h.on_done = lambda: claire.milestone(
        "Got hands", "Phase 4: I can check the PC, find files, open apps, files and websites, and change the "
                     "volume — and I always ask Carl first.")
    claire.hands = h
    return h
