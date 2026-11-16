@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo === Watchlist ARA 2026 ===
echo Mengunduh data terbaru seluruh emiten BEI (+-2 menit)...
py watchlist_ara.py %*
if errorlevel 1 (
  echo.
  echo Gagal. Coba tanpa unduh: "Buka Watchlist ARA.bat" --no-fetch
  pause
)
