#!/usr/bin/env python3
"""
SnowTown — ASCII 문자로 그리는 코지 크리스마스 마을 미니게임.

표준 라이브러리만 사용한다 (pip 설치 불필요).

    python3 snowtown.py             # 게임 시작 (60초 동안 선물 받기)
    python3 snowtown.py --demo      # 조작 없이 감상 모드
    python3 snowtown.py --no-color  # 색 없이 (단색 터미널)
    python3 snowtown.py --frames 3  # 화면 3프레임만 찍고 종료 (검증용)

조작: ←/→ 또는 A/D 이동, Space/W/↑ 점프, R 재시작, Q 종료
"""
from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import signal
import sys
import time

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:  # 윈도우: msvcrt 로 비동기 키 입력
    import ctypes
    import msvcrt
else:  # 유닉스: termios + select
    import select
    import termios
    import tty

# ---------------------------------------------------------------- 색

CSI = "\x1b["
RESET = CSI + "0m"


class Palette:
    """트루컬러 → 256색 → 단색으로 자동 강등."""

    def __init__(self, mode: str = "auto", bg_enabled: bool = True):
        self.bg_enabled = bg_enabled
        if mode == "auto":
            ct = os.environ.get("COLORTERM", "").lower()
            mode = "truecolor" if ("truecolor" in ct or "24bit" in ct) else "256"
        self.mode = mode

    def bg_code(self, rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        if self.mode == "none" or not self.bg_enabled:
            return ""
        if self.mode == "truecolor":
            return f"{CSI}48;2;{r};{g};{b}m"
        idx = 16 + 36 * (r * 5 // 255) + 6 * (g * 5 // 255) + (b * 5 // 255)
        return f"{CSI}48;5;{idx}m"

    def fg(self, rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        if self.mode == "none":
            return ""
        if self.mode == "truecolor":
            return f"{CSI}38;2;{r};{g};{b}m"
        # 256색 근사 (6x6x6 큐브)
        idx = 16 + 36 * (r * 5 // 255) + 6 * (g * 5 // 255) + (b * 5 // 255)
        return f"{CSI}38;5;{idx}m"


# ---------------------------------------------------------------- 캔버스


class Canvas:
    """문자 + 색 셀 그리드."""

    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.ch = [[" "] * w for _ in range(h)]
        self.co = [None] * (w * h)
        self.bg = [None] * (w * h)

    def put(self, x: int, y: int, ch: str, color=None, bg=None) -> None:
        """배경색은 명시할 때만 바꾼다 (하늘 위에 별·건물을 덧그릴 때 유지)."""
        if 0 <= x < self.w and 0 <= y < self.h:
            self.ch[y][x] = ch
            self.co[y * self.w + x] = color
            if bg is not None:
                self.bg[y * self.w + x] = bg

    def text(self, x: int, y: int, s: str, color=None) -> None:
        for i, c in enumerate(s):
            self.put(x + i, y, c, color)

    def cell(self, x: int, y: int):
        i = y * self.w + x
        return self.ch[y][x], self.co[i], self.bg[i]


# ---------------------------------------------------------------- 색 상수

C_SNOW = (238, 243, 255)
C_SNOW_DIM = (196, 206, 228)
C_STAR = (170, 182, 214)
C_MOON = (248, 244, 214)
C_BODY = (74, 82, 108)
C_BODY_DARK = (56, 62, 84)
C_ROOF = (226, 232, 246)
C_WINDOW = (255, 202, 92)
C_WINDOW_OFF = (96, 100, 122)
C_TREE = (58, 150, 112)
C_TREE_DARK = (40, 112, 84)
C_HAT = (226, 74, 74)
C_COAT = (206, 216, 236)
C_GIFT_A = (232, 78, 78)
C_GIFT_B = (96, 190, 130)
C_SPARK = (255, 236, 170)
C_HUD = (232, 238, 252)
C_GOOD = (140, 226, 160)

GROUND_H = 3


def lerp(a, b, t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# ---------------------------------------------------------------- 마을


class Building:
    def __init__(self, x: int, w: int, h: int, seed: int):
        self.x, self.w, self.h = x, w, h
        rnd = random.Random(seed)
        self.chimney = rnd.random() < 0.5
        self.lit = [[rnd.random() < 0.75 for _ in range(w)] for _ in range(h)]
        self.phase = [[rnd.random() * 6.28 for _ in range(w)] for _ in range(h)]
        self.tree = rnd.random() < 0.35


class World:
    """마을 배치 + 눈 + 플레이어 상태."""

    def __init__(self, w: int, h: int, seed: int | None = None):
        self.w, self.h = w, h
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.build()
        self.snow = [self._new_flake(True) for _ in range(max(8, w // 3))]
        self.sparks: list[list[float]] = []
        self.reset_player()

    # --- 지형
    def build(self) -> None:
        rnd = random.Random(self.seed)
        self.ground_y = self.h - GROUND_H
        self.buildings: list[Building] = []
        self.trees: list[tuple[int, int]] = []
        max_h = max(4, min(13, self.ground_y - 6))
        x = 2
        i = 0
        while x < self.w - 8:
            bw = rnd.randint(5, 9)
            bh = rnd.randint(4, max_h)
            if x + bw > self.w - 2:
                bw = self.w - 2 - x
            if bw < 5:
                break
            self.buildings.append(Building(x, bw, bh, self.seed + i * 977))
            i += 1
            gap = rnd.randint(4, 8)
            # 넓은 빈터에만 소나무
            if gap >= 5:
                tx = x + bw + gap // 2
                if tx < self.w - 3:
                    self.trees.append((tx, rnd.randint(3, 6)))
            x += bw + gap
        self.stars = [
            (rnd.randrange(self.w), rnd.randrange(max(1, self.ground_y - 3)), rnd.random() * 6.28)
            for _ in range(self.w // 2)
        ]
        self.moon_x = max(3, self.w - rnd.randint(4, 9))
        self.moon_y = rnd.randint(1, max(2, self.ground_y // 3))
        self.ground = [
            ["=" if rnd.random() < 0.7 else "-" for _ in range(self.w)]
            for _ in range(GROUND_H)
        ]

    def reset_player(self) -> None:
        self.px = self.w // 2
        self.py = float(self.ground_y - 3)
        self.vy = 0.0
        self.on_ground = True

    # --- 눈
    def _new_flake(self, anywhere: bool = False) -> list[float]:
        return [
            random.uniform(0, self.w - 1),
            random.uniform(0, self.ground_y) if anywhere else -1.0,
            random.uniform(1.6, 4.6),
            random.uniform(-0.5, 0.5),
            random.choice([".", ".", ".", "·", "*"]),
        ]

    # --- 갱신
    def update(self, dt: float, t: float) -> None:
        for f in self.snow:
            f[1] += f[2] * dt
            f[0] += f[3] * dt
            if f[1] > self.ground_y - 1:
                nf = self._new_flake()
                f[0], f[1], f[2], f[3], f[4] = nf
            if f[0] < 0:
                f[0] += self.w
            elif f[0] > self.w - 1:
                f[0] -= self.w

        # 플레이어 물리
        self.vy += 34.0 * dt
        self.py += self.vy * dt
        if self.py >= self.ground_y - 3:
            self.py = float(self.ground_y - 3)
            self.vy = 0.0
            self.on_ground = True
        else:
            self.on_ground = False

        for s in list(self.sparks):
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[4] -= dt
            if s[4] <= 0:
                self.sparks.remove(s)

    def jump(self) -> None:
        if self.on_ground:
            self.vy = -13.5
            self.on_ground = False

    def move(self, dx: int) -> None:
        self.px = max(1, min(self.w - 4, self.px + dx))

    def sparkle(self, x: float, y: float, n: int = 10) -> None:
        for _ in range(n):
            a = random.uniform(0, 6.283)
            sp = random.uniform(2, 7)
            self.sparks.append([x, y, math.cos(a) * sp, math.sin(a) * sp * 0.5, random.uniform(0.25, 0.6)])

    # --- 그리기
    def sky_color(self, y: int, t: float) -> tuple[int, int, int]:
        # 90초 주기로 밤 → 새벽 → 밤
        k = (math.sin(t * 2 * math.pi / 90.0 - math.pi / 2) + 1) / 2
        top = lerp((12, 16, 40), (54, 34, 78), k)
        bot = lerp((36, 46, 88), (176, 112, 100), k)
        f = y / max(1, self.ground_y)
        col = lerp(top, bot, f ** 0.8)
        # 지평선 근처 따뜻한 기운 (마을 불빛)
        glow = max(0.0, (f - 0.72) / 0.28) * 0.5
        return lerp(col, (92, 62, 62), glow)

    def draw(self, cv: Canvas, t: float, hud: str = "") -> None:
        # 하늘 (배경색으로 칠해야 터미널에서 보인다)
        for y in range(self.ground_y):
            col = self.sky_color(y, t)
            for x in range(cv.w):
                cv.put(x, y, " ", None, col)
        # 별
        for sx, sy, ph in self.stars:
            if sy < self.ground_y - 3:
                b = (math.sin(t * 2.4 + ph) + 1) / 2
                cv.put(sx, sy, ".", lerp((78, 86, 116), C_STAR, b))
        # 달
        mx, my = self.moon_x, self.moon_y
        for dx, dy, ch in [(-1, -1, "·"), (0, -1, "-"), (1, -1, "·"), (-1, 0, "/"), (0, 0, "O"), (1, 0, "\\"), (0, 1, "·")]:
            cv.put(mx + dx, my + dy, ch, C_MOON)

        # 먼 언덕 (부드러운 실루엣, 건물 뒤)
        hc = lerp((38, 44, 74), (66, 74, 108), 0.35)
        for hx in range(cv.w):
            hh = 1 + int(0.9 * (1 + math.sin(hx / 19.0 + (self.seed % 11))))
            for k in range(hh):
                cv.put(hx, self.ground_y - 1 - k, "~", hc)

        # 건물
        for b in self.buildings:
            top = self.ground_y - b.h
            for y in range(top, self.ground_y):
                for x in range(b.x, b.x + b.w):
                    edge = x in (b.x, b.x + b.w - 1)
                    cv.put(x, y, "#", C_BODY_DARK if edge else C_BODY)
            # 지붕 눈 (처마까지) + 가랜드 조명
            lights = [(255, 96, 96), (255, 206, 96), (120, 220, 140), (150, 190, 255)]
            for x in range(b.x - 1, b.x + b.w + 1):
                cv.put(x, top - 1, "~", C_ROOF)
            for j, x in enumerate(range(b.x, b.x + b.w, 2)):
                c = lights[(j + b.x) % len(lights)]
                ph = b.phase[0][j % b.w]
                b_ = 0.55 + 0.45 * math.sin(t * 2.2 + ph)
                cv.put(x, top - 1, "*", lerp((70, 74, 96), c, b_))
            # 굴뚝 + 연기
            if b.chimney and b.h >= 5:
                cx = b.x + b.w - 2
                cv.put(cx, top - 2, "|", C_BODY_DARK)
                cv.put(cx, top - 3, "_", C_ROOF)
                smoke = int((t * 1.6) % 4)
                for i in range(smoke):
                    cv.put(cx, top - 4 - i, "o" if i % 2 else "°", lerp(C_ROOF, (110, 116, 140), i / 4))
            # 창문 (3칸 간격, 반짝임)
            for wy in range(top + 2, self.ground_y - 1, 3):
                for wx in range(b.x + 2, b.x + b.w - 1, 3):
                    on = b.lit[wy % b.h][wx % b.w]
                    ph = b.phase[wy % b.h][wx % b.w]
                    flick = 0.72 + 0.28 * math.sin(t * 1.7 + ph)
                    if on:
                        cv.put(wx, wy, "o", lerp(C_WINDOW_OFF, C_WINDOW, flick))
                    else:
                        cv.put(wx, wy, ".", lerp((52, 56, 74), C_WINDOW_OFF, 0.5))
            # 문
            dx = b.x + b.w // 2
            cv.put(dx, self.ground_y - 1, "n", lerp(C_WINDOW_OFF, C_WINDOW, 0.5))

        # 소나무 (빈터에만): 폭 3, 위로 갈수록 좁아짐
        for tx, th in self.trees:
            for i in range(th):
                w = 1 if i >= th - 2 else 3
                for d in range(-(w // 2), w // 2 + 1):
                    ch = "*" if (i + d) % 2 == 0 else "^"
                    cv.put(tx + d, self.ground_y - 1 - i, ch, C_TREE if d else C_TREE_DARK)
            cv.put(tx, self.ground_y - 2 - th, ".", C_ROOF)
            cv.put(tx, self.ground_y - 1 - th, "*", C_SPARK)

        # 지면 눈: 표면은 밝게, 아래로 갈수록 어둡게 (배경색으로 두께감)
        for y in range(self.ground_y, cv.h):
            depth = y - self.ground_y
            if depth == 0:
                bg = (128, 140, 176)
                fg = C_SNOW
            elif depth == 1:
                bg = (74, 84, 118)
                fg = C_SNOW_DIM
            else:
                bg = (40, 46, 70)
                fg = lerp(C_SNOW_DIM, (120, 130, 158), 0.5)
            for x in range(cv.w):
                cv.put(x, y, self.ground[depth][x], fg if (x + y) % 3 else C_SNOW, bg)

        # 선물
        for g in getattr(self, "gifts", []):
            gx, gy = int(g[0]), int(g[1])
            cv.put(gx, gy, "[", C_GIFT_A)
            cv.put(gx + 1, gy, "]", C_GIFT_B)

        # 플레이어
        px, py = int(self.px), int(self.py)
        cv.put(px, py, "o", C_HAT)
        cv.put(px, py + 1, "|", C_COAT)
        cv.put(px - 1, py + 1, "/", C_COAT)
        cv.put(px + 1, py + 1, "\\", C_COAT)
        cv.put(px - 1, py + 2, "/", C_COAT)
        cv.put(px + 1, py + 2, "\\", C_COAT)

        # 반짝임
        for s in self.sparks:
            cv.put(int(s[0]), int(s[1]), "*", C_SPARK)

        # 눈송이
        for f in self.snow:
            cv.put(int(f[0]), int(f[1]), f[4], C_SNOW)

        if hud:
            cv.text(2, 0, hud, C_HUD)


# ---------------------------------------------------------------- 렌더러


def render_ansi(cv: Canvas, pal: Palette) -> str:
    """행마다 절대 좌표로 이동해 그린다.

    개행(\n)에 의존하면 터미널의 자동 줄바꿈과 겹쳐 행이 밀리거나 화면이
    스크롤되는 문제가 생긴다(특히 macOS Terminal.app). 절대 좌표 + 줄 끝
    지우기(EL)로 프레임을 겹쳐 그리면 그런 문제가 없다.
    """
    out = []
    for y in range(cv.h):
        out.append(f"{CSI}{y + 1};1H")
        last_fg = last_bg = None
        for x in range(cv.w):
            ch, col, bg = cv.cell(x, y)
            if bg != last_bg or col != last_fg:
                out.append(RESET)
                if bg:
                    out.append(pal.bg_code(bg))
                if col:
                    out.append(pal.fg(col))
                last_fg, last_bg = col, bg
            out.append(ch)
        out.append(RESET + CSI + "K")
    return "".join(out)


def render_text(cv: Canvas) -> str:
    return "\n".join("".join(cv.cell(x, y)[0] for x in range(cv.w)) for y in range(cv.h))


def render_html(cv: Canvas) -> str:
    return _render_html(cv)


def _render_html(cv: Canvas, cell_w: int = 9, cell_h: int = 18) -> str:
    """미리보기용 HTML (스크린샷으로 변환해 눈으로 확인)."""
    rows = []
    for y in range(cv.h):
        spans = []
        last = None
        for x in range(cv.w):
            ch, col, bg = cv.cell(x, y)
            c = "rgb(%d,%d,%d)" % col if col else "transparent"
            b = "rgb(%d,%d,%d)" % bg if bg else "transparent"
            style = f"color:{c};background-color:{b}"
            esc = {"&": "&amp;", "<": "&lt;", ">": "&gt;", " ": "&nbsp;"}.get(ch, ch)
            if style != last:
                if last is not None:
                    spans.append("</span>")
                spans.append(f'<span style="{style}">')
                last = style
            spans.append(esc)
        if last is not None:
            spans.append("</span>")
        rows.append("".join(spans))
    return (
        "<html><head><meta charset='utf-8'><style>"
        "body{margin:0;background:#05060c;}"
        f"pre{{margin:0;font:{cell_h}px/{cell_h}px 'DejaVu Sans Mono',monospace;"
        f"letter-spacing:{(cell_w - cell_h * 0.6):.2f}px;white-space:pre;}}"
        "</style></head><body><pre>" + "\n".join(rows) + "</pre></body></html>"
    )


# ---------------------------------------------------------------- 게임


class Game:
    ROUND = 60.0

    def __init__(self, w: int, h: int, demo: bool = False, seed: int | None = None):
        self.w, self.h = w, h
        self.demo = demo
        self.world = World(w, h, seed)
        self.t = 0.0
        self.score = 0
        self.missed = 0
        self.left = self.ROUND
        self.gifts: list[list[float]] = []
        self.spawn_at = 0.0
        self.over = False

    def resize(self, w: int, h: int) -> None:
        if (w, h) == (self.w, self.h):
            return
        self.w, self.h = w, h
        self.world = World(w, h, self.world.seed)
        self.world.gifts = self.gifts

    def update(self, dt: float) -> None:
        self.t += dt
        self.world.gifts = self.gifts

        if not self.demo and not self.over:
            self.left -= dt
            if self.left <= 0:
                self.left = 0
                self.over = True
            self.spawn_at -= dt
            if self.spawn_at <= 0:
                self.spawn_at = random.uniform(0.75, 1.6)
                self.gifts.append([random.uniform(2, self.w - 4), 1.0, random.uniform(3.0, 5.5)])

        self.world.update(dt, self.t)

        px, py = self.world.px, self.world.py
        for g in list(self.gifts):
            g[1] += g[2] * dt
            # 잡기
            if abs(g[0] - px) < 2.2 and abs(g[1] - (py + 1)) < 1.6:
                self.gifts.remove(g)
                self.score += 1
                self.world.sparkle(g[0], g[1], 12)
            elif g[1] >= self.world.ground_y - 1:
                self.gifts.remove(g)
                self.missed += 1

    def hud(self) -> str:
        if self.demo:
            return "SnowTown · 감상 모드 · Q 종료"
        if self.over:
            return f"SnowTown · 끝! 점수 {self.score} · R 다시하기 · Q 종료"
        return (
            f"SnowTown  선물 {self.score}  놓침 {self.missed}  남은시간 {int(self.left):2d}s"
            "   ←/→ 이동  Space 점프  Q 종료"
        )

    def draw(self) -> Canvas:
        cv = Canvas(self.w, self.h)
        self.world.gifts = self.gifts
        self.world.draw(cv, self.t, self.hud())
        if self.over:
            msg = [f"  점수 {self.score}  ", " R 다시하기 ", " Q 종료 "]
            bx = max(1, (self.w - 16) // 2)
            by = max(2, self.world.ground_y // 2 - 2)
            cv.text(bx, by, "┌" + "─" * 14 + "┐", C_GOOD)
            for i, m in enumerate(msg):
                cv.text(bx + 1, by + 1 + i, "│" + m.ljust(14) + "│", C_GOOD)
            cv.text(bx, by + 4, "└" + "─" * 14 + "┘", C_GOOD)
        return cv


# ---------------------------------------------------------------- 터미널


class Terminal:
    """터미널 제어: 크기, raw 모드, 비동기 키 입력 (유닉스/윈도우 공용).

    키 토큰: 'LEFT' 'RIGHT' 'UP' 'DOWN' 또는 문자 1개 ('q', ' ', 'a' ...)
    """

    def __init__(self, use_alt: bool = True) -> None:
        self.use_alt = use_alt
        self.windows = IS_WINDOWS
        self._old_attr = None
        self._old_in_mode = None
        self._old_out_mode = None
        self._win_kernel = None

    # --- 준비
    def setup(self) -> None:
        if self.windows:
            self._setup_windows()
        else:
            fd = sys.stdin.fileno()
            self._old_attr = termios.tcgetattr(fd)
            tty.setraw(fd)
        # ?7l = 자동 줄바꿈 끔, ?1049h = 대체 화면(옵션), ?25l = 커서 숨김
        seq = CSI + "?7l" + CSI + "?25l" + CSI + "2J"
        if self.use_alt:
            seq = CSI + "?7l" + CSI + "?1049h" + CSI + "?25l" + CSI + "2J"
        sys.stdout.write(seq)
        sys.stdout.flush()

    def _setup_windows(self) -> None:
        """콘솔 코드페이지 UTF-8 + VT 시퀀스 허용 + 입력 에코/라인모드 해제."""
        k = ctypes.windll.kernel32
        self._win_kernel = k
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        STD_OUT, STD_IN = -11, -10
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_LINE_INPUT, ENABLE_ECHO_INPUT = 0x0002, 0x0004

        h_out = k.GetStdHandle(STD_OUT)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h_out, ctypes.byref(mode)):
            self._old_out_mode = mode.value
            k.SetConsoleMode(h_out, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)

        h_in = k.GetStdHandle(STD_IN)
        imode = ctypes.c_uint32()
        if k.GetConsoleMode(h_in, ctypes.byref(imode)):
            self._old_in_mode = imode.value
            k.SetConsoleMode(h_in, imode.value & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT))

    # --- 복원
    def restore(self) -> None:
        tail = RESET + CSI + "?7h" + CSI + "?25h"
        if self.use_alt:
            tail += CSI + "?1049l"
        sys.stdout.write(tail)
        sys.stdout.flush()
        if self.windows:
            k = self._win_kernel
            if k is not None:
                if self._old_out_mode is not None:
                    k.SetConsoleMode(k.GetStdHandle(-11), self._old_out_mode)
                if self._old_in_mode is not None:
                    k.SetConsoleMode(k.GetStdHandle(-10), self._old_in_mode)
        elif self._old_attr is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_attr)

    # --- 키 입력 (논블로킹)
    def read_keys(self) -> list[str]:
        return self._read_keys_windows() if self.windows else self._read_keys_unix()

    def _read_keys_windows(self) -> list[str]:
        keys: list[str] = []
        special = {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT"}
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # 확장 키 접두
                nxt = msvcrt.getwch() if msvcrt.kbhit() else ""
                token = special.get(nxt)
                if token:
                    keys.append(token)
                continue
            if ch == "\x03":  # Ctrl+C
                keys.append("q")
                continue
            keys.append(ch)
        return keys

    def _read_keys_unix(self) -> list[str]:
        keys: list[str] = []
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0)[0]:
            data = os.read(fd, 16)
            if not data:
                break
            text = data.decode("utf-8", "ignore")
            i = 0
            while i < len(text):
                ch = text[i]
                if ch == "\x1b" and text[i + 1 : i + 2] == "[":
                    code = text[i + 2 : i + 3]
                    token = {"A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT"}.get(code)
                    if token:
                        keys.append(token)
                    i += 3
                    continue
                keys.append(ch)
                i += 1
        return keys


def term_size() -> tuple[int, int]:
    """실제 터미널 크기. 창보다 크게 그리면 줄바꿈되어 화면이 깨지므로
    임의로 키우지 않는다 (아주 작을 때만 최소값으로 방어)."""
    try:
        s = os.get_terminal_size(sys.__stdout__.fileno())
    except (OSError, ValueError, AttributeError):
        s = shutil.get_terminal_size((80, 24))
    return max(20, s.columns), max(8, s.lines - 1)


def apply_key(game: "Game", key: str, args) -> "Game":
    """키 토큰 → 게임 동작. 새 게임이 필요하면 반환한다."""
    if key in ("q", "Q", "\x03"):
        raise KeyboardInterrupt
    if key in ("a", "A", "LEFT"):
        game.world.move(-2)
    elif key in ("d", "D", "RIGHT"):
        game.world.move(2)
    elif key in ("w", "W", " ", "UP"):
        game.world.jump()
    elif key in ("r", "R") and game.over:
        return Game(game.w, game.h, demo=game.demo, seed=game.world.seed)
    return game


def run(args) -> int:
    pal = Palette("none" if args.no_color else "auto", bg_enabled=not args.no_bg)

    # 검증용: 프레임 몇 장만 찍고 종료
    if args.frames:
        w, h = args.width, args.height
        game = Game(w, h, demo=args.demo, seed=args.seed)
        for i in range(args.frames):
            game.update(1 / 12)
            if i == args.frames - 1:
                print(render_text(game.draw()) if args.no_color else render_ansi(game.draw(), pal), end="")
        print()
        return 0

    if not sys.stdout.isatty():
        print("터미널(TTY)이 아니라서 게임을 실행할 수 없습니다. --frames 로 화면만 확인할 수 있습니다.")
        return 1

    w, h = term_size()
    game = Game(w, h, demo=args.demo, seed=args.seed)
    term = Terminal(use_alt=not args.no_alt)
    old_winch = None

    def on_winch(_sig, _frm):
        nw, nh = term_size()
        game.resize(nw, nh)

    try:
        term.setup()
        if not IS_WINDOWS:
            old_winch = signal.getsignal(signal.SIGWINCH)
            signal.signal(signal.SIGWINCH, on_winch)

        last = time.monotonic()
        while True:
            now = time.monotonic()
            dt = min(0.1, now - last)
            last = now

            for key in term.read_keys():
                game = apply_key(game, key, args)

            if IS_WINDOWS:  # 윈도우는 SIGWINCH가 없어 주기적으로 크기 확인
                game.resize(*term_size())

            game.update(dt)
            sys.stdout.write(render_ansi(game.draw(), pal))
            sys.stdout.flush()
            time.sleep(max(0.0, 1 / 24 - (time.monotonic() - now)))
    except KeyboardInterrupt:
        return 0
    finally:
        if old_winch is not None:
            signal.signal(signal.SIGWINCH, old_winch)
        term.restore()


def main() -> int:
    ap = argparse.ArgumentParser(description="SnowTown — ASCII 코지 크리스마스 마을")
    ap.add_argument("--demo", action="store_true", help="조작 없이 감상 모드")
    ap.add_argument("--no-color", action="store_true", help="색 없이 출력")
    ap.add_argument("--no-bg", action="store_true", help="배경색(하늘·눈밭) 없이 출력 — 배경색이 깨지는 터미널용")
    ap.add_argument("--no-alt", action="store_true", help="대체 화면(alt screen) 없이 실행 — 화면이 겹치는 터미널용")
    ap.add_argument("--frames", type=int, default=0, help="검증용: N프레임만 출력하고 종료")
    ap.add_argument("--width", type=int, default=100)
    ap.add_argument("--height", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
