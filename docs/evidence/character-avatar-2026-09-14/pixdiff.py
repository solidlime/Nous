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

    python pixdiff.py                     # the pairs quoted in the plan
    python pixdiff.py A.png B.png         # any single pair
    python pixdiff.py stats A.png [B.png ...]   # single-image readout below
    python pixdiff.py stats --box=x0,y0,x1,y1 A.png [B.png ...]  # limit to a region

``stats`` counts the **character region** (the same non-background test as
above) and reports its luminance distribution, plus two extremes that matter
for the lighting complaints:

* ``black``: share of the character region with luminance **< 26** (a failed
  shader renders the silhouette black).
* ``white``: share with luminance **>= 240** (blown-out pixels).

For the 2026-09-15 evidence the avatar canvas sits at ``--box=317,233,863,450``
(the screenshot is 1264x569 CSS px; re-read it with
``document.querySelector('#chat-avatar-layer canvas').getBoundingClientRect()``
if the window size changes). Without ``--box`` the whole screenshot is counted,
which is dominated by the chat UI chrome and useless for character claims.
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
    # 2026-09-15: rim blow-out -> cel shading (see the plan's "照明過剰" section).
    ("rim on -> rim off (blow-out source)", "13-before-rim-on-amb-2.827.png", "14-before-rim-off.png"),
    (
        "clobbered shader: ambient 2.827 -> 0 (false 'light independent')",
        "15-clobbered-onbeforecompile-amb-2.827.png",
        "16-clobbered-onbeforecompile-amb-0.png",
    ),
    (
        "cel shading: ambient 2.827 -> 0 (true light independence)",
        "17-cel-fixed-amb-2.827.png",
        "18-cel-fixed-amb-0.png",
    ),
    (
        "cel shading: ambient 2.827 -> 0 (clock frozen at 1234.5ms)",
        "19-cel-frozen-amb-2.827.png",
        "20-cel-frozen-amb-0.png",
    ),
]

BUCKETS = [
    (0, 26),
    (26, 51),
    (51, 76),
    (76, 102),
    (102, 128),
    (128, 153),
    (153, 178),
    (178, 204),
    (204, 230),
    (230, 256),
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
    lum = luminance(b)  # int32 に広げてから輝度を取る（int16 は乗算で溢れる）
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


def luminance(a: np.ndarray) -> np.ndarray:
    # int16 のままだと 255*299 が溢れて負値になる（旧 compare() の dark_ratio は
    # この溢れで常に 1.000 に見えていた）。演算前に int32 へ広げること。
    a = a.astype(np.int32)
    return (a[..., 0] * 299 + a[..., 1] * 587 + a[..., 2] * 114) // 1000


def parse_box(token: str) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (int(v) for v in token.split(","))
    return x0, y0, x1, y1


def stats(path: str | Path, box: tuple[int, int, int, int] | None = None) -> dict[str, object]:
    """Character-region luminance readout (the numbers the plan quotes)."""
    a = load(path)
    if box is not None:
        x0, y0, x1, y1 = box
        a = a[y0:y1, x0:x1]
    region = np.abs(a - BG).max(axis=2) > BG_TOL
    lum = luminance(a)[region]
    total = int(lum.size)
    if total == 0:
        raise SystemExit(f"no character pixels in {path}")
    pct = {p: int(np.percentile(lum, p)) for p in (10, 25, 50, 75, 90)}
    buckets = {f"{lo}-{hi - 1}": 100.0 * int(((lum >= lo) & (lum < hi)).sum()) / total for lo, hi in BUCKETS}
    return {
        "char_px": total,
        "mean": float(lum.mean()),
        "pct": pct,
        "black": 100.0 * int((lum < 26).sum()) / total,
        "white": 100.0 * int((lum >= 240).sum()) / total,
        "buckets": buckets,
    }


def main(argv: list[str]) -> int:
    box = None
    args = list(argv[1:])
    if args and args[0].startswith("--box="):
        box = parse_box(args.pop(0)[len("--box=") :])
    if box is not None and (not args or args[0] != "stats"):
        raise SystemExit("--box= only applies to the stats mode")
    if args and args[0] == "stats":
        for path in args[1:]:
            s = stats(path, box)
            pct = s["pct"]
            print(
                f"{Path(path).name}: char_px={s['char_px']} mean={s['mean']:.1f} "
                f"p10/25/50/75/90={pct[10]}/{pct[25]}/{pct[50]}/{pct[75]}/{pct[90]} "
                f"black={s['black']:.1f}% white={s['white']:.1f}%"
            )
            for label, share in s["buckets"].items():
                print(f"    {label:>9}: {share:5.1f}% {'#' * int(share / 2)}")
        return 0
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
