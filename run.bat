@echo off
rem SnowTown 실행 (윈도우) — 더블클릭하거나: run.bat --demo
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 snowtown.py %*
) else (
  python snowtown.py %*
)
if errorlevel 1 (
  echo.
  echo [오류] 실행에 실패했습니다. Python 3.8+ 가 설치되어 있고 PATH에 있는지 확인하세요.
  echo   설치:  winget install Python.Python.3.12
  pause
)
