"""Pixel-difference readout for the character-avatar verification evidence.

Definitions (every pixel number quoted in
``docs/superpowers/plans/2026-09-14-character-avatar-quality.md`` comes from here):

* ``non-background``: a pixel whose largest channel differs from the chat
  background (``#1c1c1e``) by **more than 6**.
* ``changed``: a pixel whose largest channel differs between the two images by
  **more than 16** (out of 255).
* ``dark``: among the changed pixels, the share whose luminance (BT.601,
  post-change image) is **below 100**.

Usage::

    python pixdiff.py                     # the five pairs quoted in the plan
    python pixdiff.py A.png B.png         # any single pair
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

BG = np.array([0x1C, 0x1C, 0x1E], dtype=np.int16)
BG_TOL = 6
DIFF_TOL = 16
DARK_CUT = 100

HERE = Path(__file__).resolve().parent

PAIRS: list[tuple[str, str, str]] = [
    ("outline width 0 -> 0.012", "04-outline-w-0.png", "05-outline-w-0.012-default.png"),
    ("outline width 0.012 -> 0.012 (control)", "05-outline-w-0.012-default.png", "06-outline-w-0.012-control.png"),
    ("outline width 0 -> 0.03", "04-outline-w-0.png", "07-outline-w-0.03.png"),
    ("idle frame 0 -> frame 1", "08-idle-frame-0.png", "09-idle-frame-1.png"),
    ("idle frozen a -> b (control)", "10-idle-frozen-control-a.png", "11-idle-frozen-control-b.png"),
]


def load(path: str | Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def compare(a: np.ndarray, b: np.ndarray) -> dict[str, object]:
    if a.shape != b.shape:
        raise SystemExit(f"size mismatch: {a.shape} vs {b.shape}")
    nonbg = (np.abs(a - BG).max(axis=2) > BG_TOL).sum()
    chan = np.abs(b - a).max(axis=2)
    changed = chan > DIFF_TOL
    total = int(changed.sum())
    lum = (b[..., 0] * 299 + b[..., 1] * 587 + b[..., 2] * 114) // 1000
    dark = int((changed & (lum < DARK_CUT)).sum())
    ys, xs = np.nonzero(changed)
    bbox = None if total == 0 else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return {
        "changed": total,
        "nonbg_px": int(nonbg),
        "changed_pct_of_nonbg": 100.0 * total / max(int(nonbg), 1),
        "dark_ratio": None if total == 0 else dark / total,
        "bbox": bbox,
    }


def main(argv: list[str]) -> int:
    if len(argv) == 3:
        jobs = [(f"{Path(argv[1]).name} -> {Path(argv[2]).name}", Path(argv[1]), Path(argv[2]))]
    elif len(argv) == 1:
        jobs = [(label, HERE / fa, HERE / fb) for label, fa, fb in PAIRS]
    else:
        print(__doc__)
        return 2

    for label, fa, fb in jobs:
        a, b = load(fa), load(fb)
        r = compare(a, b)
        dark = "-" if r["dark_ratio"] is None else f"{r['dark_ratio']:.3f}"
        print(
            f"{label}: changed={r['changed']}px "
            f"({r['changed_pct_of_nonbg']:.2f}% of {r['nonbg_px']} non-bg) "
            f"dark_ratio={dark} bbox={r['bbox']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
