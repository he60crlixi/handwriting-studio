@echo off
chcp 65001 >nul
title 手写工坊 · 本地版
cd /d "%~dp0"

set PY=C:\Users\LeiD\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=python

echo ============================================
echo   手写工坊 · 本地版
echo   启动后浏览器会自动打开
echo   关闭此窗口即停止服务
echo ============================================
echo.

start "" http://127.0.0.1:8765/
"%PY%" server.py --port 8765
pause
