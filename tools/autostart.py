#!/usr/bin/env python
"""ADHD panosu — PC acilisinda otomatik baslatma (Windows).

Kullanim:
    python D:/ADHD/tools/autostart.py install     # (veya: python app.py --autostart install)
    python D:/ADHD/tools/autostart.py status
    python D:/ADHD/tools/autostart.py uninstall

Ne yapar:  D:\\ADHD\\start_boot.vbs dosyasini olusturur ve Windows Baslatma klasorune
(Start Menu\\Programs\\Startup) bir kopyasini birakir. PC acilisinda pencere 4 sn
gecikmeyle gizli surecte baslar (konsol penceresi cikmaz), pano acilir.

Not: Pano zaten calisiyorsa (port dolu) yeni surec hata vermez, calisan panoyu gosterir.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
VBS_SRC = BASE / "start_boot.vbs"
ENTRY_NAME = "ADHD Pano.vbs"

VBS_TEMPLATE = """\' ADHD panosu — Windows acilisinda otomatik baslatma (tools/autostart.py uretti)
\' Konsolsuz calisir; log: D:\\ADHD\\data\\pano.log
Option Explicit
Dim sh, fso, q, cmd, py, app, bootDelay
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
q = Chr(34)
py = "{python}"
app = "{app}"
bootDelay = {delay}

\' Surucu / ag hazir olmasi icin kisa bekleme
WScript.Sleep bootDelay

If Not fso.FileExists(app) Then WScript.Quit 1

If fso.FileExists(py) Then
  cmd = q & py & q & " " & q & app & q & " --window"
Else
  cmd = q & py & q & " " & q & app & q & " --window --browser"
End If

\' 0 = gizli pencere (konsol cikmaz), False = bekleme
sh.Run cmd, 0, False
"""


def startup_dir() -> Path:
    return Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))


def resolve_python() -> Path:
    """Mumkunse .venv (pywebview icin), yoksa calisan python."""
    venv = BASE / ".venv" / "Scripts"
    for name in ("pythonw.exe", "python.exe"):
        p = venv / name
        if p.exists():
            return p
    exe = Path(sys.executable)
    if exe.name.lower().startswith("python"):
        sibling = exe.with_name("pythonw.exe")
        if sibling.exists():
            return sibling
    return exe


def build_vbs(python: Path, delay_ms: int = 4000) -> str:
    return VBS_TEMPLATE.format(python=str(python), app=str(BASE / "app.py"), delay=delay_ms)


def install() -> int:
    py = resolve_python()
    VBS_SRC.write_text(build_vbs(py), encoding="utf-8")
    target = startup_dir() / ENTRY_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(VBS_SRC, target)
    except OSError as exc:
        print(f"[HATA] Baslatma klasorune yazilamadi: {exc}")
        return 1
    print("[OK] PC acilisinda baslatildi.")
    print(f"     Baslatma girdisi : {target}")
    print(f"     Kaynak           : {VBS_SRC}")
    print(f"     Python           : {py}")
    print("     Kaldirmak icin   : python tools/autostart.py uninstall")
    return 0


def uninstall() -> int:
    target = startup_dir() / ENTRY_NAME
    removed = False
    if target.exists():
        try:
            target.unlink()
            removed = True
        except OSError as exc:
            print(f"[HATA] silinemedi: {exc}")
            return 1
    print("[OK] Baslatma girdisi kaldirildi." if removed else "[BILGI] zaten kayitli degil.")
    print(f"     {target}")
    return 0


def status() -> int:
    target = startup_dir() / ENTRY_NAME
    py = resolve_python()
    print(f"Baslatma girdisi : {'VAR' if target.exists() else 'YOK'}  ({target})")
    print(f"Kaynak vbs       : {'VAR' if VBS_SRC.exists() else 'YOK'}  ({VBS_SRC})")
    print(f"Python           : {py}  ({'VAR' if py.exists() else 'YOK'})")
    print(f"pywebview        : {'VAR' if (BASE / '.venv').exists() else 'YOK (tarayici modu kullanilir)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ADHD panosu otomatik baslatma")
    ap.add_argument("action", choices=["install", "uninstall", "status"], nargs="?", default="status")
    ap.add_argument("--port", type=int, default=0, help="(gereksiz; app.py tarafindan gecilir)")
    args = ap.parse_args(argv)
    if sys.platform != "win32":
        print("[UYARI] Otomatik baslatma yalnizca Windows'ta kurulur.")
        print("        Linux/macOS icin start_adhd.sh dosyasini kendi baslatma araciniza ekleyin.")
        return 1 if args.action == "install" else 0
    return {"install": install, "uninstall": uninstall, "status": status}[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
