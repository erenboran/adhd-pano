"""ADHD panosu — repo taraması ve git ölçümleri.

Kurallar:
  * Sadece OKUMA komutlari (add/commit/push/reset/checkout/stash yok).
  * Her git cagrisi icin ayri timeout (config: git_timeout_sec, varsayilan 20 sn).
  * Timeout / hata halinde alanlar None kalir; panoda "bilinmiyor" olarak gosterilir,
    ASLA 0 veya tahmin yazilmaz.
  * Native git yolu MSYS cevirisi istemez: subprocess'e "D:/..." biciminde yol verilir.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

GIT_BIN = shutil.which("git") or "git"

# Nesil ayirici: commit alanlarini tek satirda guvenli tasimak icin.
SEP = "\x1f"


def _child_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"      # kimlik sorup asla takilmasin
    env["GIT_PAGER"] = "cat"
    env["GIT_OPTIONAL_LOCKS"] = "0"       # repo'ya kilit dosyasi bile yazmasin
    env["GIT_ASKPASS"] = ""
    env["LC_MESSAGES"] = "C"
    return env


def run_git(repo: str, args: list[str], timeout: float) -> dict:
    """Tek bir git komutunu calistirir. Hicbir zaman exception firlatmaz."""
    t0 = time.perf_counter()
    res = {"ok": False, "out": "", "err": "", "timed_out": False, "ms": 0}
    try:
        p = subprocess.run(
            [GIT_BIN, "-c", "core.quotepath=false", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_child_env(),
        )
        res["out"] = (p.stdout or "").strip()
        res["err"] = (p.stderr or "").strip()
        res["ok"] = p.returncode == 0
    except subprocess.TimeoutExpired:
        res["timed_out"] = True
        res["err"] = f"timeout >{timeout:g}s"
    except FileNotFoundError:
        res["err"] = "git bulunamadi"
    except Exception as exc:  # pragma: no cover - savunma
        res["err"] = f"{type(exc).__name__}: {exc}"
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res


# ---------------------------------------------------------------- discovery

def _norm(path: str) -> str:
    return os.path.normpath(path).replace("\\", "/")


def discover_repos(cfg: dict) -> dict:
    """config.json'daki roots'lari maxdepth'e kadar tarar, .git iceren klasorleri doner."""
    skip = {d.lower() for d in cfg.get("scan_skip_dirs", [])}
    root_depths = cfg.get("root_depths") or {}
    default_depth = int(cfg.get("scan_maxdepth", 3))
    t0 = time.perf_counter()
    repos: list[str] = []
    scanned_dirs = 0
    errors: list[str] = []

    def walk(cur: str, depth: int, maxdepth: int) -> None:
        nonlocal scanned_dirs
        try:
            entries = list(os.scandir(cur))
        except (PermissionError, OSError) as exc:
            errors.append(f"{cur}: {type(exc).__name__}")
            return
        scanned_dirs += 1
        if os.path.exists(os.path.join(cur, ".git")):
            repos.append(_norm(cur))
        if depth >= maxdepth:
            return
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = e.name
            if name in (".git",) or name.lower() in skip or name.startswith("$"):
                continue
            walk(e.path, depth + 1, maxdepth)

    for root in cfg.get("roots", []):
        # "D:/" -> "D:\\" (surucu koku); aksi halde rstrip surucu kokunu "D:" yapar ve
        # scandir("D:") o surucunun CALISMA klasorunu tarar (sessiz yanlis tarama).
        root = os.path.normpath(os.path.expanduser(root.strip()))
        if not os.path.isdir(root):
            errors.append(f"{root}: yok")
            continue
        maxdepth = default_depth
        for key in (root, root + "/", root + "\\", os.path.normpath(root).replace("\\", "/")):
            if key in root_depths:
                maxdepth = int(root_depths[key])
                break
        walk(root, 0, maxdepth)

    # Ayni repo iki root'tan da gorulebilir -> tekille
    seen, uniq = set(), []
    for r in repos:
        key = r.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(r)

    return {
        "repos": sorted(uniq),
        "discovery_sec": round(time.perf_counter() - t0, 2),
        "dirs_visited": scanned_dirs,
        "errors": errors,
    }


# ------------------------------------------------------------------ metrics

def repo_metrics(repo: str, cfg: dict) -> dict:
    """Tek repo icin salt-okunur olcumler. Okunamayan alan None kalir."""
    timeout = float(cfg.get("git_timeout_sec", 20))
    days = int(cfg.get("yapilanlar_days", 7))
    per_repo_cap = int(cfg.get("commits_per_repo", 25))

    m = {
        "path": repo,
        "name": os.path.basename(repo.rstrip("/\\")) or repo,
        "branch": None,
        "head": None,
        "last_commit_iso": None,
        "last_commit_subject": None,
        "dirty": None,
        "remote": None,
        "commits_7d": None,
        "commits_7d_capped": False,
        "commits_7d_list": [],
        "git_repo": None,
        "timeout": False,
        "errors": [],
        "ms": 0,
    }
    t0 = time.perf_counter()

    def note(r: dict, label: str) -> bool:
        if r["timed_out"]:
            m["timeout"] = True
            m["errors"].append(f"{label}: {r['err']}")
            return False
        if not r["ok"]:
            m["errors"].append(f"{label}: {r['err'][:160] or 'hata'}")
            return False
        return True

    r = run_git(repo, ["rev-parse", "--is-inside-work-tree"], timeout)
    if not r["ok"]:
        if r["timed_out"]:
            note(r, "git")
        m["git_repo"] = False
        m["errors"] = ["git deposu değil (ölçüm yok)"] + m["errors"]
        m["ms"] = int((time.perf_counter() - t0) * 1000)
        return m
    m["git_repo"] = True

    r = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout)
    if note(r, "branch"):
        m["branch"] = r["out"] or None

    r = run_git(repo, ["log", "-1", f"--format=%h{SEP}%cI{SEP}%s"], timeout)
    if note(r, "son commit") and r["out"]:
        parts = r["out"].split(SEP)
        m["head"] = parts[0] or None
        m["last_commit_iso"] = parts[1] if len(parts) > 1 else None
        m["last_commit_subject"] = parts[2] if len(parts) > 2 else None

    # Sadece takip edilen degisiklikler: devasa untracked yigini taramayi yavaslatmasin.
    r = run_git(repo, ["status", "--porcelain", "--untracked-files=no"], timeout)
    if note(r, "status"):
        m["dirty"] = len([l for l in r["out"].splitlines() if l.strip()])

    r = run_git(repo, ["remote", "get-url", "origin"], timeout)
    if r["ok"] and r["out"]:
        m["remote"] = r["out"]

    r = run_git(
        repo,
        ["log", f"--since={days}.days", f"--format=%h{SEP}%cI{SEP}%s", f"--max-count={per_repo_cap}"],
        timeout,
    )
    if note(r, f"son {days} gun"):
        lines = [l for l in r["out"].splitlines() if l.strip()]
        m["commits_7d"] = len(lines)
        m["commits_7d_capped"] = len(lines) >= per_repo_cap
        for l in lines:
            p = l.split(SEP)
            m["commits_7d_list"].append(
                {
                    "repo": m["name"],
                    "path": repo,
                    "sha": p[0] if p else None,
                    "date": p[1] if len(p) > 1 else None,
                    "subject": p[2] if len(p) > 2 else None,
                }
            )

    m["ms"] = int((time.perf_counter() - t0) * 1000)
    return m


# ----------------------------------------------------------------- snapshot

def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class DiscoveryCache:
    """Klasor taramasi pahali (~5-6 sn) -> ayri ve daha uzun TTL ile onbellege alinir."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data = None
        self._ts = 0.0
        self.last_sec = None

    def get(self, cfg: dict) -> dict:
        with self._lock:
            fresh = self._data is not None and (time.time() - self._ts) < self.ttl
            if fresh:
                return self._data
        data = discover_repos(cfg)
        with self._lock:
            self._data = data
            self._ts = time.time()
            self.last_sec = data["discovery_sec"]
        return data


def build_snapshot(cfg: dict, discovery: DiscoveryCache) -> dict:
    """Tum repo'lari olcup tek bir JSON'a cevirir (gh verisi app tarafinda eklenir veya burada)."""
    t0 = time.perf_counter()
    disc = discovery.get(cfg)
    archived = {_norm(p).lower() for p in cfg.get("archived", [])}
    hint = {_norm(p).lower(): _norm(p) for p in cfg.get("active_hint", [])}

    # Aktif adaylar: config'deki active_hint + taramada bulunan (arsivlenmemis) repolar
    candidates: list[str] = []
    seen = set()
    for p in cfg.get("active_hint", []):
        key = _norm(p).lower()
        if key not in seen and os.path.isdir(p):
            seen.add(key)
            candidates.append(_norm(p))
    for p in disc["repos"]:
        key = p.lower()
        if key in seen or key in archived:
            continue
        seen.add(key)
        candidates.append(p)
    missing_hints = [
        _norm(p) for p in cfg.get("active_hint", []) if not os.path.isdir(p)
    ]

    workers = max(1, int(cfg.get("scan_workers", 4)))
    results: list[dict] = []
    lock = threading.Lock()

    def job(path: str) -> None:
        try:
            m = repo_metrics(path, cfg)
        except Exception as exc:  # asla patlamasin
            m = {
                "path": path,
                "name": os.path.basename(path),
                "branch": None,
                "head": None,
                "last_commit_iso": None,
                "last_commit_subject": None,
                "dirty": None,
                "remote": None,
                "commits_7d": None,
                "commits_7d_list": [],
                "timeout": False,
                "errors": [f"{type(exc).__name__}: {exc}"],
                "ms": 0,
            }
        m["is_hint"] = path.lower() in hint
        with lock:
            results.append(m)

    threads = []
    queue = list(candidates)
    qlock = threading.Lock()

    def worker() -> None:
        while True:
            with qlock:
                if not queue:
                    return
                path = queue.pop(0)
            job(path)

    for _ in range(min(workers, max(1, len(queue)))):
        th = threading.Thread(target=worker, daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join()

    results.sort(key=lambda m: (not m.get("is_hint"), m["name"].lower()))

    gecmis = []
    for m in results:
        gecmis.extend(m["commits_7d_list"])
    gecmis.sort(key=lambda c: (c["date"] or ""), reverse=True)

    timeouts = [m["name"] for m in results if m["timeout"]]
    duration = round(time.perf_counter() - t0, 2)
    limit = int(cfg.get("yapilanlar_limit", 60))
    shown = gecmis[:limit]
    return {
        "generated_at": _iso_now(),
        "_ts": time.time(),
        "scan": {
            "duration_sec": duration,
            "discovery_sec": disc["discovery_sec"],
            "repos_scanned": len(results),
            "repos_discovered": len(disc["repos"]),
            "git_repos": len([m for m in results if m.get("git_repo")]),
            "not_git": [m["name"] for m in results if m.get("git_repo") is False],
            "archived": sorted(
                {
                    os.path.basename(p.rstrip("/\\").replace("\\", "/"))
                    for p in cfg.get("archived", [])
                }
            ),
            "discovered_other": [
                p for p in disc["repos"] if p.lower() in archived
            ],
            "timeouts": timeouts,
            "timeout_count": len(timeouts),
            "workers": workers,
            "git_timeout_sec": float(cfg.get("git_timeout_sec", 20)),
            "cache_ttl_sec": float(cfg.get("cache_ttl_sec", 60)),
            "missing_hint_paths": missing_hints,
            "dirs_visited": disc["dirs_visited"],
            "errors": (disc["errors"] + [e for m in results for e in m["errors"]])[:40],
            "oldest_repo_ms": max([m["ms"] for m in results], default=None),
            "yapilanlar_total": len(gecmis),
            "yapilanlar_capped": len(gecmis) > limit,
        },
        "projects": [{k: v for k, v in m.items() if k != "commits_7d_list"} for m in results],
        "yapilanlar": shown,
    }
