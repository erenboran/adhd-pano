#!/usr/bin/env python
"""ADHD — yerel kisisel kontrol panosu (Notion benzeri fikir / gorev / proje takibi).

ONEMLI: Harici bagimlilik YOKTUR. Flask, pip kurulumu, CDN, internet gerekmez;
yalnizca Python standart kutuphanesi kullanilir. Boylece PC acilisinda her kosulda
calisir (python modulu eksik olma hatasi artik mumkun degil).

Calistirma:
    python app.py                 # pencere varsa masaustu penceresi, yoksa tarayici
    python app.py --window        # masaustu pencere (pywebview kurulu olmali)
    python app.py --browser       # varsayilan tarayicida ac
    python app.py --no-browser    # yalnizca sunucu (arayuz acma)
    python app.py --port 5099 --host 127.0.0.1 --scan-now
    python app.py --autostart install   # PC acilisinda baslat / uninstall / status

Notlar:
  * git cagrilari salt okunur (add/commit/push/reset yok).
  * Pano asla taramayi beklemez; /api/state ilk saniyede doner.
  * Port zaten doluysa hata vermez, calisan panoyu gosterir (cift acilim korumasi).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import ghclient  # noqa: E402
import scanner  # noqa: E402
from db import Store  # noqa: E402

APP_TITLE = "ADHD — Kontrol Panosu"

DEFAULTS = {
    "port": 5077,
    "host": "127.0.0.1",
    "cache_ttl_sec": 60,
    "discovery_ttl_sec": 300,
    "scan_workers": 4,
    "git_timeout_sec": 20,
    "scan_maxdepth": 3,
    "yapilanlar_days": 7,
    "yapilanlar_limit": 60,
    "commits_per_repo": 25,
    "ideas_limit": 200,
    "roots": [],
    "root_depths": {},
    "archived": [],
    "active_hint": [],
    "scan_skip_dirs": [],
    "github": {"enabled": True, "timeout_sec": 15, "repos_limit": 15},
}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _txt(value, limit: int) -> str | None:
    """istemciden gelen metni temizler: kirpilir, fazla bosluk sikistirilir, None olabilir."""
    s = " ".join(str(value or "").split())
    if not s:
        return None
    return s[:limit]


def _int(value, lo: int, hi: int) -> int | None:
    """guvenli int donusumu — aralik disinda veya sayi degilse None (uydurma yok)."""
    if value in (None, ""):
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _task_flags(t: dict) -> str:
    """gorev satirina proje + ADHD alanlarini ekler (Hermes export'u icin)."""
    bits = []
    if t.get("project"):
        bits.append(str(t["project"]))
    if t.get("first_step"):
        bits.append(f"ilk adim: {t['first_step']}")
    if t.get("cue"):
        bits.append(f"uyari: {t['cue']}")
    if t.get("estimate_min"):
        bits.append(f"tahmin {t['estimate_min']} dk")
    if t.get("due_at"):
        bits.append(f"son {t['due_at']}")
    if t.get("started_at"):
        bits.append(f"baslatildi {str(t['started_at'])[:16].replace('T', ' ')}")
    return ("  — " + " · ".join(bits)) if bits else ""


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = BASE / "config.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in raw.items() if v is not None})
            cfg["github"] = {**DEFAULTS["github"], **(raw.get("github") or {})}
        except Exception as exc:  # config bozuksa varsayilanlarla devam
            print(f"[UYARI] config.json okunamadi ({exc}); varsayilanlar kullaniliyor", flush=True)
    return cfg


# ------------------------------------------------------------------ logging

_LOG_LOCK = threading.Lock()
LOG_PATH = ""


def _init_log() -> str:
    log_dir = BASE / "data"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "pano.log"
    try:
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            log_path.replace(log_dir / "pano.log.1")
    except OSError:
        pass
    return str(log_path)


def log(msg: str) -> None:
    line = f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _LOG_LOCK:
        try:
            print(line, flush=True)
        except Exception:
            pass  # pythonw (gizli konsol) modunda stdout yok
        if LOG_PATH:
            try:
                with open(LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass


# -------------------------------------------------------------- state store

class StateStore:
    """Tarama arka planda yapilir; /api/state ASLA taramayi beklemez (pano donmaz)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ttl = float(cfg.get("cache_ttl_sec", 60))
        self.discovery = scanner.DiscoveryCache(float(cfg.get("discovery_ttl_sec", 300)))
        self._lock = threading.Lock()
        self._snapshot: dict | None = None
        self._refreshing = False
        self._last_error: str | None = None
        self.refresh_count = 0
        self.on_refresh = None  # tarama bitince cagrilir (ornek: Hermes export yazimi)

    def state(self, force: bool = False) -> dict:
        self.kick(force=force)
        with self._lock:
            return {
                "snapshot": self._snapshot,
                "refreshing": self._refreshing,
                "error": self._last_error,
                "age_sec": None
                if self._snapshot is None
                else round(time.time() - self._snapshot["_ts"], 2),
            }

    def kick(self, force: bool = False) -> None:
        with self._lock:
            if self._refreshing:
                return
            fresh = (
                self._snapshot is not None
                and not force
                and (time.time() - self._snapshot["_ts"]) < self.ttl
            )
            if fresh:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> None:
        t0 = time.perf_counter()
        snap: dict | None = None
        try:
            snap = scanner.build_snapshot(self.cfg, self.discovery)
            try:
                snap["github"] = ghclient.github_state(self.cfg)
            except Exception as exc:
                snap["github"] = {"enabled": True, "binary": None, "error": f"{type(exc).__name__}: {exc}"}
            snap["scan"]["wall_sec"] = round(time.perf_counter() - t0, 2)
            with self._lock:
                self._snapshot = snap
                self._last_error = None
                self.refresh_count += 1
            log(
                f"tarama #{self.refresh_count} tamam: {snap['scan']['repos_scanned']} repo, "
                f"sure {snap['scan']['wall_sec']}s, timeout {snap['scan']['timeout_count']}"
            )
        except Exception as exc:
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
            log(f"[HATA] tarama basarisiz: {type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._refreshing = False
        if snap is not None and self.on_refresh:
            try:
                self.on_refresh(snap)
            except Exception as exc:  # export hatasi pano yonunu etkilemesin
                log(f"[UYARI] export yazilamadi: {type(exc).__name__}: {exc}")


# ----------------------------------------------------------------- http katmani

def json_resp(obj, status: int = 200) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8")


def text_resp(text: str, status: int = 200, ctype: str = "text/plain; charset=utf-8") -> tuple[int, str, bytes]:
    return status, ctype, text.encode("utf-8")


def bin_resp(data: bytes, ctype: str) -> tuple[int, str, bytes]:
    return 200, ctype, data


class Ctx:
    """Tek bir HTTP isteginin baglami."""

    def __init__(self, method: str, path: str, query: dict, params: dict, raw: bytes):
        self.method = method
        self.path = path
        self.query = query
        self.params = params
        self.raw = raw

    @property
    def force(self) -> bool:
        return str(self.query.get("force", "")).lower() in ("1", "true", "yes")

    def body(self) -> dict:
        raw = (self.raw or b"").decode("utf-8", "replace")
        if raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            try:
                form = urllib.parse.parse_qs(raw, keep_blank_values=True)
                if form:
                    return {k: v[-1] for k, v in form.items()}
            except Exception:
                pass
        return {}


class App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store(str(BASE / "data" / "adhd.db"), str(BASE / "data" / "fikirler.md"))
        self.state = StateStore(cfg)
        self.state.on_refresh = self.write_export
        self.export_path = BASE / "data" / "pano.md"
        self._export_lock = threading.Lock()
        self.routes = [
            ("GET", re.compile(r"^/$"), self.r_index),
            ("GET", re.compile(r"^/static/(?P<name>.+)$"), self.r_static),
            ("GET", re.compile(r"^/favicon\.ico$"), self.r_favicon),
            ("GET", re.compile(r"^/api/state$"), self.r_state),
            ("GET", re.compile(r"^/api/health$"), self.r_health),
            ("GET", re.compile(r"^/api/export$"), self.r_export),
            ("POST", re.compile(r"^/api/refresh$"), self.r_refresh),
            ("POST", re.compile(r"^/api/ideas$"), self.r_add_idea),
            ("DELETE", re.compile(r"^/api/ideas/(?P<idea_id>\d+)$"), self.r_del_idea),
            ("POST", re.compile(r"^/api/now$"), self.r_set_now),
            ("POST", re.compile(r"^/api/tasks$"), self.r_add_task),
            ("POST", re.compile(r"^/api/tasks/(?P<task_id>\d+)/toggle$"), self.r_toggle_task),
            ("POST", re.compile(r"^/api/tasks/(?P<task_id>\d+)/update$"), self.r_update_task),
            ("POST", re.compile(r"^/api/tasks/(?P<task_id>\d+)/start$"), self.r_start_task),
            ("DELETE", re.compile(r"^/api/tasks/(?P<task_id>\d+)$"), self.r_del_task),
            ("POST", re.compile(r"^/api/focus/start$"), self.r_focus_start),
            ("POST", re.compile(r"^/api/focus/stop$"), self.r_focus_stop),
        ]

    # -------------------------------------------------------------- dispatch
    def handle(self, method: str, target: str, raw: bytes = b"") -> tuple[int, str, bytes]:
        parts = urllib.parse.urlsplit(target)
        path = urllib.parse.unquote(parts.path)
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parts.query, keep_blank_values=True).items()}
        allowed: set[str] = set()
        for m, rx, fn in self.routes:
            mt = rx.match(path)
            if not mt:
                continue
            allowed.add(m)
            if m != method:
                continue
            ctx = Ctx(method, path, query, mt.groupdict(), raw)
            try:
                return fn(ctx)
            except Exception as exc:
                log(f"[HATA] {method} {path}: {type(exc).__name__}: {exc}")
                return json_resp({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
        if allowed:
            return json_resp({"ok": False, "error": "yontem uygun degil"}, 405)
        return json_resp({"ok": False, "error": "yok: " + path}, 404)

    # ------------------------------------------------------------- statik dosya
    def _file(self, root: Path, rel: str, ctype: str | None = None):
        try:
            root_r = root.resolve()
            target = (root_r / rel).resolve()
            # ortak yol kontrolu: "D:\ADHD" ile "D:\ADHD_gizli" karistmasin
            if os.path.commonpath([str(target), str(root_r)]) != str(root_r):
                return json_resp({"ok": False, "error": "yok"}, 404)
        except Exception:
            return json_resp({"ok": False, "error": "yok"}, 404)
        if not target.is_file():
            return json_resp({"ok": False, "error": "yok"}, 404)
        kind = ctype or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind = kind + ("; charset=utf-8" if "charset" not in kind else "")
        try:
            return bin_resp(target.read_bytes(), kind)
        except OSError as exc:
            return json_resp({"ok": False, "error": f"okunamadi: {exc}"}, 500)

    def r_index(self, ctx: Ctx):
        return self._file(BASE / "templates", "index.html", "text/html; charset=utf-8")

    def r_favicon(self, ctx: Ctx):
        p = BASE / "static" / "favicon.svg"
        if p.is_file():
            return self._file(BASE / "static", "favicon.svg", "image/svg+xml")
        return json_resp({"ok": False, "error": "yok"}, 404)

    def r_static(self, ctx: Ctx):
        return self._file(BASE / "static", ctx.params["name"])

    # ------------------------------------------------------------------ okuma
    def r_state(self, ctx: Ctx):
        st = self.state.state(force=ctx.force)
        snap = st["snapshot"]
        payload = {
            "ok": True,
            "server_time": iso_now(),
            "ready": snap is not None,
            "refreshing": st["refreshing"],
            "scan_error": st["error"],
            "cached_age_sec": st["age_sec"],
            "config": {
                "port": self.cfg.get("port"),
                "host": self.cfg.get("host"),
                "roots": self.cfg.get("roots"),
                "cache_ttl_sec": self.cfg.get("cache_ttl_sec"),
                "git_timeout_sec": self.cfg.get("git_timeout_sec"),
                "yapilanlar_days": self.cfg.get("yapilanlar_days"),
            },
            "scan": (snap or {}).get("scan") or {"state": "ilk tarama suruyor", "generated_at": None},
            "scan_generated_at": (snap or {}).get("generated_at"),
            "projects": (snap or {}).get("projects", []),
            "yapilanlar": (snap or {}).get("yapilanlar", []),
            "github": (snap or {}).get(
                "github", {"enabled": True, "error": "bilinmiyor (tarama suruyor)", "repos": []}
            ),
            "now": self.store.get_now(),
            "ideas": self.store.list_ideas(int(self.cfg.get("ideas_limit", 200))),
            "idea_count": self.store.idea_count(),
            "tasks": self.store.list_tasks(),
            "streak": self.store.streak(),
            "focus": self.store.focus_state(),
            "uyelikler": self._uyelikler(),
            "export_path": str(self.export_path),
        }
        return json_resp(payload)

    def _uyelikler(self) -> dict:
        p = BASE / "data" / "uyelikler.json"
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
            return {"ok": True, "items": items, "error": None, "path": str(p)}
        except Exception as exc:
            return {"ok": False, "items": [], "error": f"okunamadi: {type(exc).__name__}", "path": str(p)}

    def r_health(self, ctx: Ctx):
        st = self.state.state()
        return json_resp(
            {
                "ok": True,
                "ready": st["snapshot"] is not None,
                "refreshing": st["refreshing"],
                "age_sec": st["age_sec"],
                "last_error": st["error"],
                "server_time": iso_now(),
            }
        )

    def r_export(self, ctx: Ctx):
        return text_resp(self.build_export(), 200, "text/markdown; charset=utf-8")

    def r_refresh(self, ctx: Ctx):
        self.state.kick(force=True)
        return json_resp({"ok": True, "started": True})

    # ------------------------------------------------------------------ yazma
    def r_add_idea(self, ctx: Ctx):
        data = ctx.body()
        text = str(data.get("text") or "").strip()
        if not text:
            return json_resp({"ok": False, "error": "text bos"}, 400)
        if len(text) > 500:
            return json_resp({"ok": False, "error": "text cok uzun (max 500)"}, 400)
        idea = self.store.add_idea(text, source=str(data.get("source") or "panel"))
        log(f"fikir eklendi #{idea['id']}: {idea['md_line']}")
        self.write_export()
        return json_resp({"ok": True, "idea": idea, "md_path": str(BASE / "data" / "fikirler.md")})

    def r_del_idea(self, ctx: Ctx):
        idea_id = int(ctx.params["idea_id"])
        ok = self.store.delete_idea(idea_id)
        log(f"fikir silindi #{idea_id}: {'ok' if ok else 'bulunamadi'}")
        if ok:
            self.write_export()
        return json_resp({"ok": ok}, 200 if ok else 404)

    def r_set_now(self, ctx: Ctx):
        data = ctx.body()
        now = self.store.set_now(data.get("text"))
        log(f"su an guncellendi: {now['text']!r}")
        self.write_export()
        return json_resp({"ok": True, "now": now})

    def r_add_task(self, ctx: Ctx):
        data = ctx.body()
        text = str(data.get("text") or "").strip()
        if not text:
            return json_resp({"ok": False, "error": "text bos"}, 400)
        if len(text) > 300:
            return json_resp({"ok": False, "error": "text cok uzun (max 300)"}, 400)
        project = str(data.get("project") or "").strip() or None
        task = self.store.add_task(
            text, project,
            first_step=_txt(data.get("first_step"), 200),
            cue=_txt(data.get("cue"), 200),
            estimate_min=_int(data.get("estimate_min"), 1, 600),
            due_at=_txt(data.get("due_at"), 40),
        )
        log(f"gorev eklendi #{task['id']}: {task['text']}" + (f" [{project}]" if project else ""))
        self.write_export()
        return json_resp({"ok": True, "task": task})

    def r_toggle_task(self, ctx: Ctx):
        res = self.store.toggle_task(int(ctx.params["task_id"]))
        if res is None:
            return json_resp({"ok": False, "error": "bulunamadi"}, 404)
        self.write_export()
        return json_resp({"ok": True, "task": res})

    def r_update_task(self, ctx: Ctx):
        """gorev alanlarini gunceller: ilk adim, uyarI, tahmin, son tarih."""
        data = ctx.body()
        tid = int(ctx.params["task_id"])
        fields = {
            k: data.get(k)
            for k in ("first_step", "cue", "estimate_min", "due_at", "project", "text")
            if k in data
        }
        if "estimate_min" in fields:
            fields["estimate_min"] = _int(fields["estimate_min"], 1, 600)
        for k in ("first_step", "cue"):
            if k in fields:
                fields[k] = _txt(fields[k], 200)
        if "due_at" in fields:
            fields["due_at"] = _txt(fields["due_at"], 40)
        if "text" in fields:
            if not (fields["text"] or "").strip():
                return json_resp({"ok": False, "error": "text bos olamaz"}, 400)
            fields["text"] = _txt(fields["text"], 300)
        if "project" in fields:
            fields["project"] = _txt(fields["project"], 60)

        task = self.store.update_task(tid, fields)
        if task is None:
            return json_resp({"ok": False, "error": "bulunamadi"}, 404)
        log(f"gorev guncellendi #{tid}: {sorted(k for k in fields)}")
        self.write_export()
        return json_resp({"ok": True, "task": task})

    def r_start_task(self, ctx: Ctx):
        """gorevi 'baslatildi' isaretler — arayuz gecen sureyi gosterir."""
        data = ctx.body()
        on = bool(data.get("on", True))
        tid = int(ctx.params["task_id"])
        task = self.store.set_started(tid, on)
        if task is None:
            return json_resp({"ok": False, "error": "bulunamadi"}, 404)
        log(f"gorev {'baslatildi' if on else 'duraklatildi'} #{tid}")
        self.write_export()
        return json_resp({"ok": True, "task": task})

    def r_focus_start(self, ctx: Ctx):
        """odak oturumu — 25 dk geri sayim (baslatma + sureyi gorunur kilma)."""
        data = ctx.body()
        minutes = _int(data.get("minutes"), 5, 120) or 25
        task_id = data.get("task_id")
        task_id = int(task_id) if str(task_id).isdigit() else None
        task_text = _txt(data.get("task_text"), 300)
        if task_id:
            t = self.store.get_task(task_id)
            if t is None:
                return json_resp({"ok": False, "error": "gorev bulunamadi"}, 404)
            task_text = t["text"]
        if not task_text:
            task_text = (self.store.get_now().get("text") or "").strip() or "odak"
        st = self.store.focus_start(task_id, task_text, minutes)
        log(f"odak basladi: {minutes} dk — {task_text}")
        self.write_export()
        return json_resp({"ok": True, "focus": st})

    def r_focus_stop(self, ctx: Ctx):
        st = self.store.focus_stop()
        log("odak kapatildi")
        self.write_export()
        return json_resp({"ok": True, "focus": st})

    def r_del_task(self, ctx: Ctx):
        ok = self.store.delete_task(int(ctx.params["task_id"]))
        if ok:
            self.write_export()
        return json_resp({"ok": ok}, 200 if ok else 404)

    # ---------------------------------------------------- Hermes export (data/pano.md)
    def build_export(self, snapshot: dict | None = None) -> str:
        """Verileri Hermes'in okuyabilecegi markdown dosyasina cevirir (uydurma yok)."""
        if snapshot is None:
            snapshot = self.state.state()["snapshot"]
        tasks = self.store.list_tasks()
        ideas = self.store.list_ideas(50)
        now = self.store.get_now()
        snap = snapshot or {}
        scan = snap.get("scan") or {}
        gh = snap.get("github") or {}
        projects = snap.get("projects") or []
        yapilan = snap.get("yapilanlar") or []

        open_t = [t for t in tasks if not t.get("done")]
        done_t = [t for t in tasks if t.get("done")]
        focus = self.store.focus_state()
        streak = self.store.streak()
        lines = [
            "# ADHD panosu — anlik durum (otomatik yazilir)",
            "",
            "Bu dosya `python app.py` calisirken her degisiklikte yeniden yazilir.",
            "Hermes / diger ajanlar buradan gorev, fikir ve proje durumunu okuyabilir.",
            "",
            f"Guncelleme: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## SU AN (tek odak)",
            f"- {now.get('text') or '_tanimli degil_'}",
            "",
            "## Odak / seri",
            "- odak: " + (
                f"{focus['minutes']} dk oturum aktif, {focus['remaining_sec']} sn kaldi"
                + (f" — {focus.get('task_text')}" if focus.get("task_text") else "")
                if focus.get("active")
                else ("sure doldu (kapatilmayi bekliyor)" if focus.get("finished") else "oturum yok")
            ),
            f"- seri: {streak['streak']} gun art arda · bugun {streak['today_done']} bitis",
            "",
            f"## Gorevler ({len(open_t)} acik / {len(tasks)} toplam)",
        ]
        if not tasks:
            lines.append("- _gorev yok_")
        for t in open_t:
            lines.append(f"- [ ] {t['text']}" + _task_flags(t))
        if done_t:
            lines.append("")
            lines.append(f"### Tamamlananlar ({len(done_t)})")
            for t in done_t:
                when = (t.get("done_at") or "")[:16].replace("T", " ")
                lines.append(f"- [x] {t['text']}" + (f"  — {when}" if when else "") + _task_flags(t))

        lines += ["", f"## Fikirler ({self.store.idea_count()} toplam, son {len(ideas)})"]
        if not ideas:
            lines.append("- _fikir yok_")
        for it in ideas:
            stamp = (it.get("created_at") or "")[:16].replace("T", " ")
            lines.append(f"- [{stamp}] {it['text']}")

        lines += ["", f"## Yapilanlar (son {self.cfg.get('yapilanlar_days', 7)} gun): {len(yapilan)} commit"]
        if not yapilan:
            lines.append("- _bu surede commit yok_")
        for c in yapilan[:40]:
            lines.append(f"- {(c.get('date') or '')[:10]}  {c.get('repo')}  {c.get('sha')}  {c.get('subject')}")

        lines += ["", "## Aktif projeler"]
        if not projects:
            lines.append("- _tarama sonucu yok (ilk tarama suruyor olabilir)_")
        for p in projects[:30]:
            bits = []
            bits.append(str(p.get("branch") or "bilinmiyor"))
            bits.append(f"degisen {p.get('dirty') if p.get('dirty') is not None else 'bilinmiyor'}")
            bits.append(f"son commit {(p.get('last_commit_iso') or 'bilinmiyor')[:16]}")
            bits.append(f"7g {p.get('commits_7d') if p.get('commits_7d') is not None else 'bilinmiyor'}")
            flags = ""
            if p.get("timeout"):
                flags += " [timeout]"
            if p.get("is_hint"):
                flags += " [aktif]"
            lines.append(f"- {p.get('name')}: " + " · ".join(bits) + flags)

        lines += [
            "",
            "## Tarama",
            f"- repo: {scan.get('repos_scanned', 'bilinmiyor')} okundu / "
            f"{scan.get('repos_discovered', 'bilinmiyor')} kesfedildi",
            f"- timeout: {scan.get('timeout_count', 'bilinmiyor')}",
            f"- son tarama: {snap.get('generated_at') or 'yok (henuz tamamlanmadi)'}",
        ]
        lines += [
            "",
            "## GitHub (gh CLI, salt okunur)",
            f"- hesap: {gh.get('account') or 'bilinmiyor'}",
            f"- giris: {gh.get('authenticated')}",
            f"- repo listesi: {gh.get('repo_count') if gh.get('repo_count') is not None else 'bilinmiyor'}",
        ]
        if gh.get("error"):
            lines.append(f"- not: {gh['error']}")
        lines.append("")
        return "\n".join(lines)

    def write_export(self, snapshot: dict | None = None) -> None:
        """data/pano.md dosyasini atomik olarak tazeler (Hermes okuması icin)."""
        with self._export_lock:
            try:
                text = self.build_export(snapshot)
                tmp = self.export_path.with_suffix(".md.tmp")
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, self.export_path)
            except Exception as exc:
                log(f"[UYARI] data/pano.md yazilamadi: {type(exc).__name__}: {exc}")


class Handler(BaseHTTPRequestHandler):
    app: App = None  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"
    server_version = "ADHD/2.0"

    def _dispatch(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            status, ctype, data = self.app.handle(self.command, self.path, raw)
        except Exception as exc:  # savunma: hicbir istek yarim kalmasin
            log(f"[HATA] istek islenemedi: {type(exc).__name__}: {exc}")
            status, ctype, data = json_resp({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = _dispatch
    do_POST = _dispatch
    do_DELETE = _dispatch
    do_PUT = _dispatch
    do_HEAD = _dispatch

    def log_message(self, fmt: str, *args) -> None:  # werkzeug/gultu yok
        if args and str(args[0]).startswith(("4", "5")):
            log(f"http {self.command} {self.path} -> " + (fmt % args))


class HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def handle_error(self, request, client_address):  # tracebacks istemiyoruz
        return


def make_http_server(app: App, host: str, port: int) -> HttpServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return HttpServer((host, port), handler)


# ------------------------------------------------------------- masaustu pencere

def webview2_available() -> bool:
    """Windows'ta Edge WebView2 runtime kurulu mu? (MSHTML/IE modern UI'yi bozar.)"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except Exception:
        return False
    guid = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + guid),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + guid),
        (winreg.HKEY_CURRENT_USER, "SOFTWARE\\" + guid),
    ]
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as key:
                pv, _ = winreg.QueryValueEx(key, "pv")
                if pv and pv != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def pywebview_installed() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def open_window(url: str, debug: bool = False) -> bool:
    """Native masaustu pencere acar. Basarisizsa False doner (tarayiciya donulur)."""
    if not pywebview_installed():
        return False
    if not webview2_available():
        # WebView2 yoksa pywebview sessizce Internet Explorer motoruna duser ve modern
        # arayuz bozulur -> bilincli olarak tarayici moduna gec.
        log("[UYARI] WebView2 runtime bulunamadi; masaustu pencere yerine tarayici acilacak.")
        return False
    import webview

    storage = BASE / ".webview"
    try:
        storage.mkdir(exist_ok=True)
    except OSError:
        pass
    try:
        webview.create_window(
            APP_TITLE,
            url,
            width=1480,
            height=950,
            min_size=(980, 640),
            easy_drag=False,
            text_select=True,
        )
    except Exception as exc:
        log(f"[UYARI] pencere olusturulamadi: {type(exc).__name__}: {exc}")
        return False
    try:
        # gui=edgechromium: modern motor zorlanir (IE'ye sessiz dusus yok).
        # private_mode=False + storage_path: tema tercihi diske yazilsin, proje icinde kalsin.
        log("masaustu pencere aciliyor (gui=edgechromium)...")
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage), debug=debug)
    except TypeError:  # eski surumlerde parametre farkliligi
        try:
            webview.start()
        except Exception as exc:
            log(f"[UYARI] masaustu pencere calistirilamadi: {type(exc).__name__}: {exc}")
            return False
    except Exception as exc:
        log(f"[UYARI] masaustu pencere calistirilamadi: {type(exc).__name__}: {exc}")
        return False
    log("masaustu pencere kapandi")
    return True


# ----------------------------------------------------------------------- main

def port_busy(host: str, port: int) -> bool:
    """Portta dinleyen biri var mi? (bind ile degil, connect ile sorulur:
    SO_REUSEADDR, Windows'ta ayni porta ikinci bir bind'e izin verdigi icin
    bind tabanli test guvenilir degildir — bu yuzden cift acilim korumasi
    onceki surumde calismiyordu.)"""
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True   # biri cevap verdi -> port dolu
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    global LOG_PATH
    cfg = load_config()
    ap = argparse.ArgumentParser(description="ADHD yerel kontrol panosu")
    ap.add_argument("--host", default=str(cfg.get("host") or "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(cfg.get("port") or 5077))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--window", action="store_true",
                      help="masaustu pencerede ac (pywebview gerekir; acilamazsa tarayiciya duser)")
    mode.add_argument("--browser", action="store_true", help="tarayicida ac")
    mode.add_argument("--no-browser", action="store_true", help="sunucuyu ac, arayuz acma")
    ap.add_argument("--debug", action="store_true",
                    help="pywebview konsol ciktisini ac (JS hatalarini gormek icin)")
    ap.add_argument("--scan-now", action="store_true", help="acilista taramayi bekle, ozet bas")
    ap.add_argument("--autostart", choices=["install", "uninstall", "status"],
                    help="PC acilisinda baslatilmayi kur/kaldir/goster")
    args = ap.parse_args(argv)

    LOG_PATH = _init_log()

    if args.autostart:
        sys.path.insert(0, str(BASE / "tools"))
        import autostart

        return autostart.main([args.autostart, "--port", str(args.port)])

    url = f"http://{args.host}:{args.port}"
    log(f"ADHD panosu basliyor: {url}  (python {sys.version.split()[0]}, log: {LOG_PATH})")

    want_window = not args.browser and not args.no_browser   # masaustu pencere denemeye deger
    want_browser = not args.no_browser                        # pencere acilmazsa tarayiciya dus

    if port_busy(args.host, args.port):
        # Cift acilim korumasi: pano zaten calisiyor -> sadece goster, hata verme.
        log(f"[BILGI] {url} zaten calisiyor; yeni surec baslatilmadi.")
        if want_window and open_window(url, args.debug):
            return 0
        if want_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        return 0

    app = App(cfg)
    app.state.kick()  # ilk tarama arka planda hemen baslasin
    app.write_export()

    if args.scan_now:
        deadline = time.time() + 120
        while time.time() < deadline:
            st = app.state.state()
            if st["snapshot"] is not None:
                sc = st["snapshot"]["scan"]
                log(
                    f"ilk tarama bitti: sure {sc['wall_sec']}s (git {sc['duration_sec']}s, "
                    f"kesif {sc['discovery_sec']}s), repo {sc['repos_scanned']}, timeout {sc['timeout_count']}"
                )
                break
            time.sleep(0.5)

    try:
        server = make_http_server(app, args.host, args.port)
    except OSError as exc:
        log(f"[HATA] sunucu baslatilamadi: {exc}")
        return 1

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="pano-http")
    thread.start()
    log(f"sunucu hazir: {url}")

    opened = False
    if want_window:
        opened = open_window(url, args.debug)
    if not opened and want_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        log("tarayici aciliyor")
    if not opened and not want_browser:
        log("arayuz acilmadi (--no-browser); sunucu arka planda calisiyor")

    try:
        if not opened:
            while True:
                time.sleep(3600)  # --no-browser / tarayici modu: sunucu ayakta kalir
    except KeyboardInterrupt:
        log("kapatildi (Ctrl+C)")
    finally:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        log("sunucu durduruldu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
