# SnowTown ❄

ASCII 문자만으로 그리는 아늑한 겨울 마을 미니게임. 표준 라이브러리만 쓰므로 설치할 것이 없습니다.

![night](shots/snowtown-night.png)
![dawn](shots/snowtown-dawn.png)

## 실행

```bash
cd "$HOME/hermes agent/snowtown"
python3 snowtown.py             # 게임 시작 (60초 동안 떨어지는 선물 받기)
python3 snowtown.py --demo      # 조작 없이 감상 (수업 프로젝션·스크린세이버용)
python3 snowtown.py --no-color  # 색 없이 (단색 터미널)
```

색은 트루컬러 → 256색 → 단색으로 자동 강등되므로 어떤 터미널에서도 동작합니다.

## 조작

| 키 | 동작 |
|---|---|
| `←` `→` 또는 `A` `D` | 좌우 이동 |
| `Space` / `W` / `↑` | 점프 |
| `R` | 게임 오버 후 다시 시작 |
| `Q` (또는 `Ctrl+C`) | 종료 |

60초 동안 하늘에서 떨어지는 선물 `[ ]`을 받으면 점수가 올라가고, 놓치면 놓침 수가 올라갑니다.
시간이 끝나면 결과 창이 뜹니다.

## 화면 구성

- **하늘**: 90초 주기로 밤 → 새벽 → 밤으로 변하는 배경 그라데이션 (배경색으로 칠함)
- **마을**: 눈 덮인 지붕(`~`), 지붕 가랜드 조명, 따뜻한 창문 불빛, 굴뚝 연기, 문, 소나무
- **날씨**: 흩날리는 눈, 별(반짝임), 달
- **플레이어**: `o` `/|\` 로 그린 작은 사람
- **지면**: 3단 눈밭 (표면이 밝고 아래로 갈수록 어두움)

## 파일 구조

```
snowtown/
├── snowtown.py          # 게임 본체 (렌더러 + 게임 루프 + 터미널 제어)
├── tools/
│   ├── preview.py       # 프레임을 HTML로 렌더 (스크린샷 검증용)
│   ├── html_shot.mjs    # HTML → PNG (headless Chromium)
│   └── pty_test.py      # PTY에서 대화형 실행·종료 경로 검증
└── shots/               # 미리보기 이미지
```

`snowtown.py`는 렌더링을 `Canvas`(문자+글자색+배경색 셀 격자)로 분리해 두었고,
같은 캔버스를 ANSI(터미널)와 HTML(미리보기) 두 가지로 출력할 수 있습니다.

## 커스터마이즈

| 바꾸고 싶은 것 | 위치 |
|---|---|
| 색감 (눈·건물·조명) | `snowtown.py` 상단 `C_*` 색 상수 |
| 라운드 시간(초) | `class Game` 의 `ROUND = 60.0` |
| 점프 세기·중력 | `World.update()` 의 `34.0`(중력), `-13.5`(점프) |
| 낮밤 주기 | `World.sky_color()` 의 `90.0` |
| 마을 밀도 | `World.build()` 의 건물 폭·간격·높이 |
| 선물 생성 빈도 | `Game.update()` 의 `random.uniform(0.75, 1.6)` |

## 검증

```bash
python3 tools/preview.py /tmp/p.html --frames 50 --seed 12   # 화면 렌더
node tools/html_shot.mjs /tmp/p.html /tmp/p.png 1010 620     # PNG 변환
python3 tools/pty_test.py                                    # 대화형 실행/종료 검증
python3 snowtown.py --frames 3 --width 60 --height 18        # 임의 크기 렌더 확인
```
