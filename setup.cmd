@echo off
setlocal
cd /d "%~dp0"
echo ==========================================================
echo  ADHD panosu kurulumu
echo  1) .venv olusturur   2) pywebview kurar (native pencere)
echo  3) testleri calistirir   4) istersen acilista baslatir
echo ==========================================================

echo.
echo [1/4] Sanal ortam (.venv) olusturuluyor...
if exist ".venv\Scripts\python.exe" (
  echo       zaten var, atlandi
) else (
  python -m venv .venv
  if errorlevel 1 (
    echo [HATA] .venv olusturulamadi. "python --version" kontrol et.
    pause
    exit /b 1
  )
)

echo [2/4] pywebview kuruluyor (masaustu pencere icin)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pywebview
if errorlevel 1 (
  echo [UYARI] pywebview kurulamadi - pano tarayicida calisacak.
)

echo [3/4] Testler calisiyor (yaklasik 1-2 dakika, port 5078)...
".venv\Scripts\python.exe" tools\smoke_test.py
set "TESTRES=%ERRORLEVEL%"

echo.
echo [4/4] PC acilisinda otomatik baslatma
choice /C YN /M "  Pano PC acilisinda otomatik acilsin mi (Y/N)"
if errorlevel 2 (
  echo       atlandi - sonra: python tools\autostart.py install
) else (
  ".venv\Scripts\python.exe" tools\autostart.py install
)

echo.
if "%TESTRES%"=="0" (
  echo [OK] Kurulum bitti. Simdi acmak icin: start_adhd.cmd
) else (
  echo [DIKKAT] Bazilari testi gecemedi - ciktida [FAIL] satirlarina bak.
)
pause
endlocal
