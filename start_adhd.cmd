@echo off
REM ADHD panosu - Windows baslatici (cift tikla)
REM Once setup.cmd ile .venv kurulursa masaustu penceresi acilir; yoksa tarayici acilir.
REM Bu pencereyi KAPATMAK sunucuyu durdurur. Log: data\pano.log
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  set "PY=python"
  where python >nul 2>nul
  if errorlevel 1 (
    echo [HATA] "python" bulunamadi. Python 3.10+ kurulu ve PATH'te olmali.
    echo         Once D:\ADHD\setup.cmd dosyasini calistirin.
    pause
    exit /b 1
  )
)

echo ADHD panosu basliyor: http://127.0.0.1:5077
echo Bu pencereyi kapatirsan pano durur. Log: %~dp0data\pano.log
"%PY%" "%~dp0app.py" %*
if errorlevel 1 (
  echo.
  echo [HATA] Pano baslatilamadi. Yukaridaki mesaja ve data\pano.log dosyasina bak.
  echo         Port doluysa config.json icindeki "port" degerini degistir.
  pause
)
endlocal
