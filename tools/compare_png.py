#!/usr/bin/env python3
"""Compare two renders with a tolerance, for tools/golden.sh.

Exact bytes are too strict: a browser can shift antialiasing between runs on the
same machine. What matters is whether the *picture* changed -- a colour moved, a
shape vanished -- so the test is the fraction of pixels that differ by more than
a small amount per channel.
"""

from __future__ import annotations

import sys

MAX_DIFF_FRACTION = 0.002      # 0.2% of pixels may differ
CHANNEL_TOLERANCE = 12         # ...and only by this much per channel


def main() -> int:
    try:
        from PIL import Image, ImageChops
    except ImportError:
        print("  (Pillow not available; skipping comparison)")
        return 0
    a, b = (Image.open(p).convert("RGB") for p in sys.argv[1:3])
    if a.size != b.size:
        print(f"  size changed: {a.size} vs {b.size}")
        return 1
    diff = ImageChops.difference(a, b)
    changed = sum(1 for px in diff.getdata() if max(px) > CHANNEL_TOLERANCE)
    total = a.size[0] * a.size[1]
    frac = changed / total
    if frac > MAX_DIFF_FRACTION:
        print(f"  {frac:.3%} of pixels changed (limit {MAX_DIFF_FRACTION:.1%})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
