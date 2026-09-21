#!/usr/bin/env python3
"""대화형 실행 경로 검증: PTY에서 게임을 띄우고 키 입력 후 Q로 정상 종료되는지 확인."""
import os
import pty
import select
import sys
import time

GAME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snowtown.py")

pid, fd = pty.fork()
if pid == 0:
    os.environ["TERM"] = "xterm-256color"
    os.environ["COLORTERM"] = "truecolor"
    os.execv(sys.executable, [sys.executable, GAME])

buf = b""
sent = False
status = None
start = time.time()

while time.time() - start < 15:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
        except OSError:
            break

    if not sent and time.time() - start > 2.5:
        os.write(fd, b"d")      # 오른쪽 이동
        time.sleep(0.3)
        os.write(fd, b" ")      # 점프
        time.sleep(0.3)
        os.write(fd, b"q")      # 종료
        sent = True

    wpid, st = os.waitpid(pid, os.WNOHANG)
    if wpid == pid:
        status = st
        break

if status is None:
    # EOF로 루프를 빠져나온 경우: 종료를 잠깐 기다렸다가 회수
    for _ in range(20):
        wpid, st = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            status = st
            break
        time.sleep(0.1)

if status is None:
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    code = "TIMEOUT"
else:
    code = os.waitstatus_to_exitcode(status)

text = buf.decode("utf-8", "ignore")
frames = text.count("\x1b[1;1H")  # 절대좌표 렌더러 기준
ok = (
    code == 0
    and frames > 20
    and "SnowTown" in text
    and "Traceback" not in text
    and "\x1b[?1049l" in text
)

print(f"exit code      : {code}")
print(f"frames rendered: {frames}")
print(f"HUD drawn      : {'SnowTown' in text}")
print(f"exception      : {'Traceback' in text}")
alt_off = "\x1b[?1049l" in text
print("alt screen off :", alt_off)
print(f"VERDICT        : {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
