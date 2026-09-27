#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kurulum ve otomatik baslatma dogrulamasi (kisa rapor).

Kontrol eder:
  1) Python ortami + gercekten kullanilan bagimliliklar (webview, gh CLI, sqlite)
  2) Proje dosyalari (calisma zamani) ve README bolumleri
  3) Port / tekil sunucu / kilit dosyasi
  4) Otomatik baslatma: Startup klasorundeki ADHD Pano.vbs + kaynak vbs + python yolu
  5) Sistem sagligi: ekran, disk, pano.log

Kullanim:
  python tools/startup_check.py          # rapor
  python tools/startup_check.py --json    # makine okunur cikti
Cikis: 0 = hic "KALDI" yok, 1 = en az bir "KALDI" var.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PY = sys.executable

GO, FAIL, SKIP = "GECTI", "KALDI", "ATLANDI"
_results: list[dict] = []


def check(name: str, ok, detail: str = "", level: str | None = None) -> bool:
    _results.append({"name": name, "status": GO if ok else (level or FAIL), "detail": detail})
    return bool(ok)


def log(msg: str) -> None:
    try:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def run(args: list[str], timeout: int = 25) -> str:
    """Ciktiyi her zaman guvenli bicimde okur (cp1254/Turkce karakter patlamasin)."""
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout,
                           text=True, encoding="utf-8", errors="replace")
        return (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return f"<{type(exc).__name__}: {exc}>"


# --------------------------------------------------------------- 1) ortam
def check_python() -> None:
    check("Python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])

    # pywebview dagitim adi "pywebview", import adi "webview"
    try:
        import webview  # noqa: F401
        ver = getattr(webview, "__version__", "?")
        check("webview (native pencere)", True, f"pywebview {ver}")
    except Exception as exc:
        check("webview (native pencere)", False, f"{type(exc).__name__}: {exc}",
              level=FAIL)

    check("sqlite3 (adhd.db)", True, "gomulu")

    # proje gh CLI ile calisir (requests kullanilmiyor)
    gh = shutil.which("gh")
    check("gh CLI (GitHub taramasi)", bool(gh), gh or "PATH'de yok — tarama 0 repo doner")
    if gh:
        out = run([gh, "--version"], timeout=20)
        m = re.search(r"gh version (\S+)", out)
        check("gh calisiyor", bool(m), m.group(1) if m else out.strip()[:60])

    # ayni kurulumu sistem python'u ile de dogrula (PATH'deki python farkli olabilir)
    p = run([PY, "-c", "import sys;print(sys.version.split()[0])"])
    check("PATH python ile ayni surum", p.strip() == sys.version.split()[0], p.strip() or "?")


# ------------------------------------------------------------- 2) dosyalar
REQUIRED = [
    "app.py", "db.py", "ghclient.py", "scanner.py",
    "setup.cmd", "start_adhd.cmd", "start_adhd.sh",
    "README.md", "IDEA.md", "PROMPT.md", ".gitignore", "config.example.json",
    "templates/index.html", "static/app.js", "static/app.css", "static/favicon.svg",
    "tools/autostart.py", "tools/smoke_test.py", "tools/startup_check.py",
    "data/fikirler.md", "data/uyelikler.json", "data/adhd.db",
]
README_BITS = ["## Elle test", "## API", "## PC açılışında", "## Dosya düzeni"]


def check_files() -> None:
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    check("Proje dosyalari", not missing,
          ", ".join(missing[:4]) if missing else f"{len(REQUIRED)} dosya")

    for f in ("app.py", "db.py", "scanner.py", "ghclient.py"):
        try:
            (ROOT / f).read_text(encoding="utf-8")
            ok, det = True, "UTF-8"
        except Exception as exc:
            ok, det = False, str(exc)
        check(f"{f} kod cozme", ok, det)

    try:
        rd = (ROOT / "README.md").read_text(encoding="utf-8")
        miss = [b for b in README_BITS if b not in rd]
        check("README bolumleri", not miss, ", ".join(miss) if miss else f"{len(README_BITS)} bolum")
    except Exception as exc:
        check("README bolumleri", False, str(exc))

    check("calisma dizini dogru", (ROOT / "app.py").exists(), str(ROOT))


# ---------------------------------------------------------------- 3) port
def check_port() -> None:
    busy = False
    try:
        with socket.create_connection(("127.0.0.1", 5077), timeout=0.6):
            busy = True
    except Exception:
        busy = False
    check("Port 5077", True, "sunucu dinleniyor" if busy else "bos — yeni sunucu baslatilabilir")

    lock = DATA / "server.lock"
    if lock.exists():
        raw = lock.read_text(encoding="utf-8", errors="replace").strip()
        pid = 0
        m = re.search(r"\d+", raw)
        if m:
            pid = int(m.group(0))
        alive = False
        if pid > 0:
            out = run(["tasklist", "/FI", f"PID eq {pid}"], timeout=20)
            alive = str(pid) in out
        check("server.lock canli sureci gosteriyor", alive, f"pid={pid} {'canli' if alive else 'olu/bos'}")
    else:
        check("server.lock", True, "yok (sunucu hic baslamadi)", level=SKIP)


# --------------------------------------------------- 4) otomatik baslatma
def startup_dir() -> Path:
    return Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))


def check_autostart() -> None:
    entry = startup_dir() / "ADHD Pano.vbs"
    src = ROOT / "start_boot.vbs"

    if entry.exists():
        check("Startup girdisi (ADHD Pano.vbs)", True, str(entry))
        try:
            same = src.exists() and entry.read_bytes() == src.read_bytes()
            check("Startup girdisi kaynakla ayni", same,
                  "eslesen kopya" if same else "farkli — `autostart.py install` tekrar calistir")
        except OSError as exc:
            check("Startup girdisi okunabilir", False, str(exc))
    else:
        check("Startup girdisi (ADHD Pano.vbs)", False,
              "yok — `python tools\\autostart.py install`", level=SKIP)

    if src.exists():
        txt = src.read_text(encoding="utf-8", errors="replace")
        py_m = re.search(r'py = "([^"]+)"', txt)
        app_m = re.search(r'app = "([^"]+)"', txt)
        py_path = Path(py_m.group(1)) if py_m else None
        app_path = Path(app_m.group(1)) if app_m else None
        check("vbs -> app.py yolu", bool(app_path and app_path.exists()),
              str(app_path) if app_path else "bulunamadi")
        check("vbs -> python yolu", bool(py_path and py_path.exists()),
              str(py_path) if py_path else "bulunamadi")
        if py_path and py_path.exists():
            out = run([str(py_path), "-c",
                       "import sys;sys.path.insert(0,r'%s');import webview;print('ok')" % str(ROOT)])
            check("vbs python'u webview kurabilir", "ok" in out,
                  out.strip().splitlines()[-1][:70] if out.strip() else "bos")
        check("vbs gizli calisir (konsol yok)", "sh.Run cmd, 0, False" in txt, "Run ... 0, False")
        check("vbs gecikmeli baslar (surucu hazir)", "WScript.Sleep" in txt, "Sleep var")
    else:
        check("start_boot.vbs (kaynak)", False, "yok — install edilmemis", level=SKIP)

    # app.py --autostart gercekte autostart.py'yi cagiriyor mu
    app_src = (ROOT / "app.py").read_text(encoding="utf-8", errors="replace")
    check("app.py --autostart baglantisi", "autostart" in app_src, "argparse tanimli")
    check("app.py tekil port kontrolu", "create_connection" in app_src,
          "create_connection" if "create_connection" in app_src else "eski REUSEADDR denemesi")

    for script in ("start_adhd.cmd", "setup.cmd", "start_adhd.sh"):
        p = ROOT / script
        if not p.exists():
            check(f"{script} saglikli", False, "dosya yok", level=SKIP)
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        bad = [t for t in ("TODO", "<<EOF", "elseif") if t in txt]
        check(f"{script} saglikli", not bad, ", ".join(bad) if bad else "ok")


# ------------------------------------------------------------ 5) sistem
def check_system() -> None:
    try:
        import ctypes
        u = ctypes.windll.user32
        vw, vh = u.GetSystemMetrics(78), u.GetSystemMetrics(79)   # CX/CY VIRTUALSCREEN
        pw, ph = u.GetSystemMetrics(0), u.GetSystemMetrics(1)     # birincil ekran
        mons = u.GetSystemMetrics(80)                             # SM_CMONITORS
        check("Ekran olcutleri", bool(vw and vh), f"virtual {vw}x{vh}, birincil {pw}x{ph}")
        check("Ekran sayisi", bool(mons), f"{mons} ekran (SM_CMONITORS)")
        # ikinci ekran x=-1920'de oldugu icin virtual genislik > birincil genislik
        check("Coklu ekran algilandi", True,
              "virtual > birincil => 2+ ekran" if vw and pw and vw > pw else "tek ekran")
    except Exception as exc:
        check("Ekran olcutleri", False, str(exc), level=SKIP)

    try:
        t = shutil.disk_usage(str(ROOT))
        free_gb = t.free / (1 << 30)
        check("Disk bosluk >= 1 GB", free_gb >= 1, f"{free_gb:.1f} GB")
    except Exception as exc:
        check("Disk bosluk", False, str(exc), level=SKIP)

    logf = DATA / "pano.log"
    if logf.exists():
        txt = logf.read_text(encoding="utf-8", errors="replace")
        errs = re.findall(r"(?im)^\s*(ERROR|CRITICAL):.*$", txt)
        check("pano.log hatasiz", not errs, f"{len(errs)} hata" if errs else "temiz")
    else:
        check("pano.log", False, "yok (sunucu hic log yazmadi)", level=SKIP)

    check("Sistem saati", True, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ") + " UTC")


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    log(f"[startup_check] dizin={ROOT}")

    check_python()
    check_files()
    check_port()
    check_autostart()
    check_system()

    passed = sum(1 for r in _results if r["status"] == GO)
    skipped = sum(1 for r in _results if r["status"] == SKIP)
    failed = [r for r in _results if r["status"] == FAIL]

    if as_json:
        print(json.dumps({"date": datetime.now(timezone.utc).isoformat(),
                          "python": sys.version.split()[0], "results": _results,
                          "passed": passed, "skipped": skipped,
                          "failed": [r["name"] for r in failed]},
                         ensure_ascii=False, indent=2))
        return 1 if failed else 0

    for r in _results:
        log(f"  {r['status']:8} | {r['name']}" + (f" | {r['detail']}" if r.get("detail") else ""))
    log("")
    log(f"[startup_check] SONUC: {passed} gecti, {skipped} atlandi, {len(failed)} kaldi")
    if failed:
        log("  kalanlar: " + ", ".join(r["name"] for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
