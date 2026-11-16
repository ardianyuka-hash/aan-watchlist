@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo === AAN Watchlist: unduh data, buat dashboard, kirim ke GitHub ===
py watchlist_ara.py --publish %*
echo.
echo Online: https://ardianyuka-hash.github.io/aan-watchlist/
pause
