#!/usr/bin/env python3
"""SnowTown 화면을 HTML로 렌더 (스크린샷 검증용).

    python3 tools/preview.py out.html [--frames 40] [--seed 7] [--w 100] [--h 30]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from snowtown import Game, render_html  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--w", type=int, default=100)
    ap.add_argument("--h", type=int, default=30)
    ap.add_argument("--demo", action="store_true", default=True)
    a = ap.parse_args()

    game = Game(a.w, a.h, demo=a.demo, seed=a.seed)
    for _ in range(a.frames):
        game.update(1 / 24)
    html = render_html(game.draw())
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {a.out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
