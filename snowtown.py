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
C_HUD = (232, 238, 252)
C_SPARK = (255, 236, 170)
C_GOOD = (140, 226, 160)
HUD_BG = (14, 18, 34)

# 아이소메트릭 면 색: (배경색, 글자색) — 배경으로 면을 채우고 글자로 질감을 준다
ROOF = ((214, 224, 244), (176, 188, 216))     # 눈 덮인 지붕
FACE_L = ((92, 100, 130), (74, 82, 110))      # 앞-왼쪽 면 (빛 받는 쪽)
FACE_R = ((64, 70, 96), (50, 56, 80))         # 앞-오른쪽 면 (그늘)
WINDOW_ON = ((255, 206, 96), (255, 238, 180))
WINDOW_OFF = ((74, 80, 104), (60, 66, 88))
DOOR = ((58, 46, 40), (120, 92, 70))
SNOW_BG = ((122, 133, 170), (152, 162, 196))
SNOW_EDGE = ((156, 167, 200), (188, 197, 224))
ROAD_BG = ((70, 76, 104), (94, 100, 130))
TREE = ((44, 110, 84), (70, 156, 116))
TRUNK = ((72, 56, 46), (96, 74, 60))
LAMP = ((255, 226, 150), (255, 244, 200))
POLE = ((70, 76, 100), (56, 62, 84))
GIFT = ((226, 74, 74), (255, 150, 140))
GIFT2 = ((96, 190, 130), (170, 240, 200))
HAT = ((226, 74, 74), (255, 160, 150))
COAT = ((206, 216, 236), (168, 180, 208))
SHADOW = ((72, 80, 112), (60, 68, 96))

# 아이소메트릭 투영 계수 (문자 셀은 세로가 길어 2:1 로 보정) — 값이 클수록 확대
AX, AY, AZ = 0.9, 0.45, 0.8

WORLD_W = 300         # 마을 길이 (월드 x)
ROAD_Y0, ROAD_Y1 = 58, 68   # 눈 치운 길 (도로) 띠 (월드 y)
ROAD_MID = (ROAD_Y0 + ROAD_Y1) / 2.0
BUILDING_ROWS = (28, 40, 50, 76, 88, 100, 112)   # 건물 줄 (월드 y)


def lerp(a, b, t: float):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class Iso:
    """월드 좌표 → 화면 좌표 (아이소메트릭) 및 역변환."""

    def __init__(self, ox: float, oy: float):
        self.ox, self.oy = ox, oy

    def pt(self, wx: float, wy: float, wz: float = 0.0) -> tuple[float, float]:
        return (self.ox + (wx - wy) * AX, self.oy + (wx + wy) * AY - wz * AZ)


# ---------------------------------------------------------------- 마을


class Building:
    def __init__(self, x: int, y: int, w: int, d: int, h: int, seed: int):
        self.x, self.y, self.w, self.d, self.h = x, y, w, d, h
        rnd = random.Random(seed)
        self.chimney = rnd.random() < 0.5
        self.phase = rnd.random() * 6.28
        self.win_l = [(i, k) for i in range(1, w) for k in range(2, h, 3)]
        self.win_r = [(j, k) for j in range(1, d) for k in range(2, h, 3)]
        self.lit = {(i, k): rnd.random() < 0.8 for i, k in self.win_l}
        self.lit_r = {(j, k): rnd.random() < 0.6 for j, k in self.win_r}


class World:
    """아이소메트릭 눈 마을 + 플레이어/눈/반짝임 상태."""

    def __init__(self, w: int, h: int, seed: int | None = None):
        self.w, self.h = w, h
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.build()
        self.snow = [self._new_flake(True) for _ in range(max(14, w // 3))]
        self.sparks: list[list[float]] = []
        self.gifts: list[list[float]] = []
        self.reset_player()

    # --- 마을 배치
    def build(self) -> None:
        rnd = random.Random(self.seed)
        self.buildings: list[Building] = []
        for tag, y0 in enumerate(BUILDING_ROWS):
            x = 4 + (tag % 3) * 5
            i = 0
            while x < WORLD_W - 10:
                bw = rnd.randint(6, 11)
                bh = rnd.randint(4, 9)
                bd = rnd.randint(5, 8)
                self.buildings.append(Building(x, y0, bw, bd, bh, self.seed + tag * 7919 + i * 977))
                x += bw + rnd.randint(3, 8)
                i += 1
        self.trees: list[tuple[int, int, int]] = []
        for x in range(6, WORLD_W - 5, 9):
            if rnd.random() < 0.65:
                ty = rnd.choice([ROAD_Y0 - 3, ROAD_Y1 + 2, 34, 46, 82, 94])
                self.trees.append((x, ty, rnd.randint(4, 7)))
        self.lamps = [x for x in range(8, WORLD_W - 6, 16)]

    def ground_cell(self, wx: int, wy: int) -> tuple[str, str]:
        """지면 한 칸의 문자와 종류(무한 눈 평면 — 필요할 때 계산)."""
        if ROAD_Y0 <= wy < ROAD_Y1:
            if wy == int(ROAD_MID) and (wx // 2) % 2 == 0:
                return "-", "road"           # 중앙 차선
            return ("." if (wx + wy) % 3 else ":"), "road"
        if wy in (ROAD_Y0 - 1, ROAD_Y1):
            return (" " if (wx * 5 + wy) % 7 else "·"), "edge"   # 길가 눈더미
        return (" " if (wx * 7 + wy * 3) % 12 else "·"), "snow"

    def reset_player(self) -> None:
        self.px = 14.0
        self.py = ROAD_MID
        self.pz = 0.0
        self.vz = 0.0
        self.on_ground = True

    # --- 눈
    def _new_flake(self, anywhere: bool = False) -> list[float]:
        return [
            random.uniform(0, self.w - 1),
            random.uniform(0, self.h * 0.8) if anywhere else -1.0,
            random.uniform(1.8, 5.0),
            random.uniform(-0.6, 0.6),
            random.choice([".", ".", ".", "·", "*"]),
        ]

    # --- 갱신
    def update(self, dt: float, t: float) -> None:
        for f in self.snow:
            f[1] += f[2] * dt
            f[0] += f[3] * dt
            if f[1] > self.h - 2:
                nf = self._new_flake()
                f[0], f[1], f[2], f[3], f[4] = nf
            if f[0] < 0:
                f[0] += self.w
            elif f[0] > self.w - 1:
                f[0] -= self.w

        if not self.on_ground or self.vz > 0:
            self.vz -= 26.0 * dt
            self.pz += self.vz * dt
            if self.pz <= 0:
                self.pz = 0.0
                self.vz = 0.0
                self.on_ground = True

        for s in list(self.sparks):
            s[0] += s[3] * dt
            s[1] += s[4] * dt
            s[2] += s[5] * dt
            s[5] -= 4.0 * dt
            s[6] -= dt
            if s[6] <= 0 or s[2] < 0:
                self.sparks.remove(s)

    def jump(self) -> None:
        if self.on_ground:
            self.vz = 9.5
            self.on_ground = False

    def move(self, dx: int) -> None:
        self.px = max(3.0, min(WORLD_W - 5.0, self.px + dx * 1.1))

    def sparkle(self, x: float, y: float, z: float = 1.6, n: int = 12) -> None:
        for _ in range(n):
            a = random.uniform(0, 6.283)
            self.sparks.append([
                x + random.uniform(-0.3, 0.3),
                y + random.uniform(-0.3, 0.3),
                z + random.uniform(-0.4, 0.6),
                math.cos(a) * 2.2,
                math.sin(a) * 1.1,
                random.uniform(0.6, 2.0),
                random.uniform(0.35, 0.8),
            ])

    # --- 하늘
    def sky_color(self, y: int, t: float) -> tuple[int, int, int]:
        k = (math.sin(t * 2 * math.pi / 90.0 - math.pi / 2) + 1) / 2
        top = lerp((12, 16, 40), (54, 34, 78), k)
        bot = lerp((40, 52, 96), (176, 112, 100), k)
        return lerp(top, bot, (y / max(1, self.h)) ** 0.7)

    # --- 면 채우기 (역매핑: 화면 격자를 훑어 월드 좌표로 되돌려 칠한다)
    def _plane_z(self, cv, iso, x, y, w, d, z, col, ch="=", clip=None) -> None:
        """z = 높이 평면의 마름모(사각형) 채우기."""
        A, B = x - y, x + y
        corners = [iso.pt(x, y, z), iso.pt(x + w, y, z), iso.pt(x + w, y + d, z), iso.pt(x, y + d, z)]
        c0 = int(min(p[0] for p in corners)) - 1
        c1 = int(max(p[0] for p in corners)) + 1
        r0 = int(min(p[1] for p in corners)) - 1
        r1 = int(max(p[1] for p in corners)) + 1
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                t = (c - iso.ox) / AX - A          # i - j
                s = (r - iso.oy + z * AZ) / AY - B  # i + j
                i, j = (s + t) / 2.0, (s - t) / 2.0
                if -0.01 <= i <= w + 0.01 and -0.01 <= j <= d + 0.01:
                    if clip and not clip(i, j):
                        continue
                    cv.put(c, r, ch, col[1] if isinstance(col, tuple) else None,
                           col[0] if isinstance(col, tuple) else col)

    def _face_j(self, cv, iso, x, yj, w, h, col, ch="#", clip=None) -> None:
        """wy = yj 인 세로면 채우기 (앞-왼쪽 면)."""
        corners = [iso.pt(x, yj, 0), iso.pt(x + w, yj, 0), iso.pt(x + w, yj, h), iso.pt(x, yj, h)]
        c0 = int(min(p[0] for p in corners)) - 1
        c1 = int(max(p[0] for p in corners)) + 1
        r0 = int(min(p[1] for p in corners)) - 1
        r1 = int(max(p[1] for p in corners)) + 1
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                i = (c - iso.ox) / AX - (x - yj)
                k = (iso.oy + (x + i + yj) * AY - r) / AZ
                if -0.01 <= i <= w + 0.01 and -0.01 <= k <= h + 0.01:
                    if clip and not clip(i, k):
                        continue
                    cv.put(c, r, ch, col[1], col[0])

    def _face_i(self, cv, iso, xi, y, d, h, col, ch="#", clip=None) -> None:
        """wx = xi 인 세로면 채우기 (앞-오른쪽 면)."""
        corners = [iso.pt(xi, y, 0), iso.pt(xi, y + d, 0), iso.pt(xi, y + d, h), iso.pt(xi, y, h)]
        c0 = int(min(p[0] for p in corners)) - 1
        c1 = int(max(p[0] for p in corners)) + 1
        r0 = int(min(p[1] for p in corners)) - 1
        r1 = int(max(p[1] for p in corners)) + 1
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                j = xi - y - (c - iso.ox) / AX
                k = (iso.oy + (xi + y + j) * AY - r) / AZ
                if -0.01 <= j <= d + 0.01 and -0.01 <= k <= h + 0.01:
                    if clip and not clip(j, k):
                        continue
                    cv.put(c, r, ch, col[1], col[0])

    def _box(self, cv, iso, x, y, w, d, h, roof, fl, fr,
             roof_ch="=", lch="#", rch="#", roof_clip=None, l_clip=None, r_clip=None) -> None:
        self._plane_z(cv, iso, x, y, w, d, h, roof, roof_ch, roof_clip)
        self._face_j(cv, iso, x, y + d, w, h, fl, lch, l_clip)
        self._face_i(cv, iso, x + w, y, d, h, fr, rch, r_clip)

    def draw(self, cv: Canvas, t: float, hud: str = "") -> None:
        # 카메라: 플레이어를 화면 중앙 하단에 고정
        ox = self.w / 2 - (self.px - self.py) * AX
        oy = self.h * 0.60 - (self.px + self.py) * AY + self.pz * AZ
        iso = Iso(ox, oy)

        # 하늘
        for y in range(cv.h):
            col = self.sky_color(y, t)
            for x in range(cv.w):
                cv.put(x, y, " ", None, col)

        # 별 / 달
        rnd = random.Random(self.seed)
        horizon = int(oy)
        for _ in range(cv.w // 2):
            sx = rnd.randrange(cv.w)
            sy = rnd.randrange(max(1, horizon - 3))
            tw = (math.sin(t * 2.4 + sx * 0.7) + 1) / 2
            cv.put(sx, sy, ".", lerp((78, 86, 116), C_STAR, tw))
        mx, my = cv.w - 13, max(2, horizon - 12)
        for dx, dy, ch in [(-1, -1, "·"), (0, -1, "-"), (1, -1, "·"), (-1, 0, "/"), (0, 0, "O"), (1, 0, "\\"), (0, 1, "·")]:
            cv.put(mx + dx, my + dy, ch, C_MOON)

        # 화면에 보이는 월드 범위만 계산 (성능)
        s_lo = (0 - oy) / AY - 2
        s_hi = (self.h - oy) / AY + 2
        t_lo = (0 - ox) / AX - 2
        t_hi = (self.w - ox) / AX + 2
        wx_lo = max(-4000, int((s_lo + t_lo) / 2) - 2)
        wx_hi = min(WORLD_W + 4000, int((s_hi + t_hi) / 2) + 3)
        wy_lo = max(-4000, int((s_lo - t_hi) / 2) - 2)
        wy_hi = min(4000, int((s_hi - t_lo) / 2) + 3)

        # 원근 안개: 멀수록(화면 위쪽) 하늘색에 가깝게 — 깊이감
        base_row = self.h * 0.60

        def haze_at(r: float) -> float:
            return max(0.0, min(1.0, (base_row - r) / max(1.0, base_row))) ** 1.15 * 0.8

        snow_cols, edge_cols, road_cols = [], [], []
        for r in range(cv.h):
            hz = haze_at(r)
            sky = self.sky_color(r, t)
            snow_cols.append((lerp(SNOW_BG[0], sky, hz), lerp(SNOW_BG[1], sky, hz)))
            edge_cols.append((lerp(SNOW_EDGE[0], sky, hz), lerp(SNOW_EDGE[1], sky, hz)))
            road_cols.append((lerp(ROAD_BG[0], sky, hz), lerp(ROAD_BG[1], sky, hz)))

        # 바닥 (무한 눈 평면 — 보이는 범위만 계산)
        put = cv.put
        cw, chh = cv.w, cv.h
        mid = int(ROAD_MID)
        for wy in range(wy_lo, wy_hi):
            on_road = ROAD_Y0 <= wy < ROAD_Y1
            edge = (wy == ROAD_Y0 - 1) or (wy == ROAD_Y1)
            lane = on_road and wy == mid
            for wx in range(wx_lo, wx_hi):
                c = ox + (wx - wy) * AX
                r = oy + (wx + wy) * AY
                rr = int(r + 0.5)
                if 0 <= rr < chh:
                    if on_road:
                        cols = road_cols[rr]
                        if lane and (wx >> 1) & 1 == 0:
                            ch = "-"
                        else:
                            ch = "." if (wx + wy) % 3 else ":"
                    elif edge:
                        cols = edge_cols[rr]
                        ch = " " if (wx * 5 + wy) % 7 else "·"
                    else:
                        cols = snow_cols[rr]
                        ch = " " if (wx * 7 + wy * 3) % 12 else "·"
                    put(int(c + 0.5), rr, ch, cols[1], cols[0])

        # 가로등 불빛 풀 (눈밭에 번지는 빛)
        for lx in self.lamps:
            if lx + 6 < wx_lo or lx - 6 > wx_hi:
                continue
            ly = ROAD_Y0 - 1
            for dy in range(-6, 7):
                for dx in range(-6, 7):
                    dist = math.hypot(dx, dy)
                    if dist > 5.5:
                        continue
                    if dist > 3.6 and (dx + dy) % 2:
                        continue          # 바깥 링은 성기게 (전송량 절감)
                    c, r = iso.pt(lx + dx * 0.5, ly + dy * 0.5, 0)
                    f = max(0.0, 1 - dist / 5.5) * 0.45
                    warm = lerp(SNOW_BG[0], (206, 176, 126), round(f * 6) / 6)  # 3~4단계
                    cv.put(int(round(c)), int(round(r)), "·", warm, warm)

        # 오브젝트 (뒤 → 앞)
        def visible(x: float, y: float, pad: float = 16.0) -> bool:
            return (wx_lo - pad) <= x <= (wx_hi + pad) and (wy_lo - pad) <= y <= (wy_hi + pad)

        items: list[tuple[float, str, object]] = []
        for b in self.buildings:
            if visible(b.x, b.y):
                items.append((b.x + b.y, "b", b))
        for tr in self.trees:
            if visible(tr[0], tr[1], 6):
                items.append((tr[0] + tr[1], "t", tr))
        for lx in self.lamps:
            if visible(lx, ROAD_Y0 - 1, 6):
                items.append((lx + ROAD_Y0 - 1, "l", lx))
        for g in self.gifts:
            items.append((g[0] + g[1], "g", g))
        items.append((self.px + self.py, "p", None))
        items.sort(key=lambda it: it[0])

        for _, kind, obj in items:
            if kind == "b":
                b = obj
                br = int(round(iso.pt(b.x, b.y, 0)[1]))
                hz = haze_at(br) if 0 <= br < cv.h else 0.0
                sky = self.sky_color(max(0, min(cv.h - 1, br)), t)

                def fade(col):
                    return (lerp(col[0], sky, hz), lerp(col[1], sky, hz))

                self._plane_z(cv, iso, b.x - 0.3, b.y - 0.3, b.w + 0.6, b.d + 0.6, 0, SHADOW, " ")
                self._box(cv, iso, b.x, b.y, b.w, b.d, b.h, fade(ROOF), fade(FACE_L), fade(FACE_R), "=", "#", "#")
                for (i, k) in b.win_l:
                    lit = b.lit[(i, k)]
                    flick = 0.72 + 0.28 * math.sin(t * 2.0 + b.phase + i * 0.6 + k)
                    bg = lerp(WINDOW_OFF[0], WINDOW_ON[0], flick) if lit else WINDOW_OFF[0]
                    fg = lerp(WINDOW_OFF[1], WINDOW_ON[1], flick) if lit else WINDOW_OFF[1]
                    bg = lerp(bg, sky, hz * 0.6)
                    fg = lerp(fg, sky, hz * 0.6)
                    c, r = iso.pt(b.x + i, b.y + b.d, k)
                    cv.put(int(round(c)), int(round(r)), "o", fg, bg)
                for (j, k) in b.win_r:
                    lit = b.lit_r[(j, k)]
                    bg = WINDOW_ON[0] if lit else WINDOW_OFF[0]
                    fg = WINDOW_ON[1] if lit else WINDOW_OFF[1]
                    bg = lerp(bg, sky, hz * 0.6)
                    fg = lerp(fg, sky, hz * 0.6)
                    c, r = iso.pt(b.x + b.w, b.y + j, k)
                    cv.put(int(round(c)), int(round(r)), "o", fg, bg)
                c, r = iso.pt(b.x + b.w // 2, b.y + b.d, 0.6)
                cv.put(int(round(c)), int(round(r)), "n", DOOR[1], DOOR[0])
                if b.chimney:
                    cx, cy = b.x + b.w - 2, b.y + b.d - 2
                    for k in range(int(b.h), int(b.h) + 2):
                        c, r = iso.pt(cx, cy, k)
                        cv.put(int(round(c)), int(round(r)), "|", POLE[1], POLE[0])
                    for i in range(int((t * 2) % 4)):
                        c, r = iso.pt(cx, cy, b.h + 2 + i)
                        cv.put(int(round(c)), int(round(r)), "o" if i % 2 else "°",
                               lerp((150, 156, 178), (80, 86, 110), i / 4), None)
            elif kind == "t":
                tx, ty, th = obj
                self._plane_z(cv, iso, tx - 0.6, ty - 0.6, 1.4, 1.4, 0, SHADOW, " ")
                for k in range(th * 2):
                    c, r = iso.pt(tx, ty, k * 0.35)
                    cv.put(int(round(c)), int(round(r)), "|", TRUNK[1], TRUNK[0])
                for lvl in range(th):
                    rad = (th - lvl) * 0.5
                    self._plane_z(cv, iso, tx - rad, ty - rad, rad * 2, rad * 2,
                                  th * 0.7 + lvl * 0.6, TREE,
                                  "*" if lvl % 2 else "^")
            elif kind == "l":
                lx, ly = obj, ROAD_Y0 - 1
                self._plane_z(cv, iso, lx - 0.4, ly - 0.4, 0.9, 0.9, 0, SHADOW, " ")
                for k in range(9):
                    c, r = iso.pt(lx, ly, k * 0.55)
                    cv.put(int(round(c)), int(round(r)), "|", POLE[1], POLE[0])
                glow = 0.7 + 0.3 * math.sin(t * 3 + lx)
                c, r = iso.pt(lx, ly, 5.1)
                cv.put(int(round(c)), int(round(r)), "*", lerp(LAMP[1], (255, 255, 235), glow), LAMP[0])
            elif kind == "g":
                gx, gy, gz = obj[0], obj[1], obj[2]
                self._plane_z(cv, iso, gx - 0.8, gy - 0.8, 2.0, 2.0, 0, SHADOW, " ")
                self._box(cv, iso, gx - 0.8, gy - 0.8, 1.6, 1.6, 2.0, GIFT, GIFT, GIFT2, "#", "#", "#")
                c, r = iso.pt(gx, gy, 2.4)
                cv.put(int(round(c)), int(round(r)), "*", C_SPARK)
            else:
                self._plane_z(cv, iso, self.px - 0.8, self.py - 0.8, 1.8, 1.8, 0, SHADOW, " ")
                bx, by = (int(round(v)) for v in iso.pt(self.px, self.py, self.pz))
                cv.put(bx, by - 4, "o", HAT[1], HAT[0])
                for dx, ch in ((-1, "/"), (0, "|"), (1, "\\")):
                    cv.put(bx + dx, by - 3, ch, COAT[1], COAT[0])
                    cv.put(bx + dx, by - 2, ch if dx else "|", COAT[1], COAT[0])

        for s in self.sparks:
            c, r = iso.pt(s[0], s[1], s[2])
            cv.put(int(round(c)), int(round(r)), "*", C_SPARK)

        for f in self.snow:
            cv.put(int(f[0]), int(f[1]), f[4], C_SNOW)

        if hud:
            for x in range(cv.w):      # 배경을 깔아 색 전환이 글자 사이에 끼지 않게
                cv.put(x, 0, " ", None, HUD_BG)
            cv.text(2, 0, hud, C_HUD)


# ---------------------------------------------------------------- 렌더러


def render_ansi(cv: Canvas, pal: Palette) -> str:
    """행마다 절대 좌표로 이동해 그린다.

    개행(\n)에 의존하면 터미널의 자동 줄바꿈과 겹쳐 행이 밀리거나 화면이
    스크롤되는 문제가 생긴다(특히 macOS Terminal.app). 절대 좌표 + 줄 끝
    지우기(EL)로 프레임을 겹쳐 그리면 그런 문제가 없다.
    """
    out = []
    fg_default = CSI + "39m"
    bg_default = CSI + "49m"
    for y in range(cv.h):
        out.append(f"{CSI}{y + 1};1H")
        last_fg = last_bg = "?"
        for x in range(cv.w):
            ch, col, bg = cv.cell(x, y)
            # 바뀐 속성만 갱신 (RESET 남발하면 전송량이 커진다)
            if col != last_fg:
                out.append(pal.fg(col) if col else fg_default)
                last_fg = col
            if bg != last_bg:
                out.append(pal.bg_code(bg) if bg else bg_default)
                last_bg = bg
            out.append(ch)
        out.append(fg_default + bg_default + CSI + "K")
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
        self.gifts: list[list[float]] = []   # [wx, wy, wz, 낙하속도]
        self.spawn_at = 0.0
        self.over = False

    def resize(self, w: int, h: int) -> None:
        if (w, h) == (self.w, self.h):
            return
        self.w, self.h = w, h
        self.world = World(w, h, self.world.seed)
        self.world.gifts = self.gifts

    def _spawn_gift(self) -> None:
        self.gifts.append([
            random.uniform(4, WORLD_W - 6),
            ROAD_MID,
            17.0,
            random.uniform(5.0, 8.0),
        ])

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
                self.spawn_at = random.uniform(0.8, 1.7)
                self._spawn_gift()

        self.world.update(dt, self.t)

        px, py, pz = self.world.px, self.world.py, self.world.pz
        for g in list(self.gifts):
            g[2] -= g[3] * dt
            # 잡기: 플레이어가 선물 아래에 있고 높이가 맞을 때
            if abs(g[0] - px) < 2.0 and g[2] <= pz + 3.2 and g[2] >= pz - 0.6:
                self.gifts.remove(g)
                self.score += 1
                self.world.sparkle(g[0], g[1], max(1.4, pz + 1.6))
            elif g[2] <= 0:
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
            by = max(2, self.h // 2 - 2)
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
            time.sleep(max(0.0, 1.0 / max(5, args.fps) - (time.monotonic() - now)))
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
    ap.add_argument("--fps", type=int, default=20, help="초당 프레임 (기본 24, 원격 접속이 느리면 15)")
    ap.add_argument("--frames", type=int, default=0, help="검증용: N프레임만 출력하고 종료")
    ap.add_argument("--width", type=int, default=100)
    ap.add_argument("--height", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
