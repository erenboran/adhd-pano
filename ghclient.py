"""ADHD panosu — GitHub durumu (SALT OKUNUR `gh` cagrilari).

Yalnizca okuma komutlari kullanilir: `gh auth status`, `gh api user`, `gh repo list`.
Hicbir yazma/PR/issue komutu yok. gh yoksa veya hata verirse alanlar None kalir
(panoda "bilinmiyor"), uydurma deger uretilmez.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time

GH_BIN = shutil.which("gh") or "gh"


def _run(args: list[str], timeout: float) -> dict:
    t0 = time.perf_counter()
    res = {"ok": False, "out": "", "err": "", "timed_out": False, "ms": 0}
    if not shutil.which("gh"):
        res["err"] = "gh bulunamadi"
        return res
    try:
        p = subprocess.run(
            [GH_BIN, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        res["out"] = (p.stdout or "").strip()
        res["err"] = (p.stderr or "").strip()
        res["ok"] = p.returncode == 0
    except subprocess.TimeoutExpired:
        res["timed_out"] = True
        res["err"] = f"timeout >{timeout:g}s"
    except Exception as exc:  # pragma: no cover
        res["err"] = f"{type(exc).__name__}: {exc}"
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res


def _parse_auth_status(text: str) -> dict:
    """`gh auth status` cikisini ayristirir (surum farklarina dayanikli)."""
    info = {"authenticated": None, "account": None, "protocol": None, "scopes": [], "token": None, "host": None}
    for raw in text.splitlines():
        line = raw.strip().lstrip("✓-*  ").strip()
        low = line.lower()
        if low.startswith("logged in to"):
            info["authenticated"] = True
            head = line.split("account", 1)
            if len(head) > 1:
                info["account"] = head[1].split()[0].strip()
            rest = line.split("to", 1)
            if len(rest) > 1:
                info["host"] = rest[1].strip().split()[0]
        elif low.startswith("active account"):
            info["authenticated"] = True
            val = line.split(":", 1)[-1].strip()
            info["authenticated"] = val.lower().startswith("true")
        elif low.startswith("git operations protocol"):
            info["protocol"] = line.split(":", 1)[-1].strip()
        elif low.startswith("token scopes"):
            info["scopes"] = [s.strip().strip("'") for s in line.split(":", 1)[-1].split(",") if s.strip()]
    return info


def github_state(cfg: dict) -> dict:
    """gh hesabini, token kapsamlarini ve (varsa) repolari doner. Asla exception firlatmaz."""
    gcfg = cfg.get("github", {}) or {}
    enabled = bool(gcfg.get("enabled", True))
    timeout = float(gcfg.get("timeout_sec", 15))
    st = {
        "enabled": enabled,
        "binary": bool(shutil.which("gh")),
        "authenticated": None,
        "account": None,
        "host": None,
        "protocol": None,
        "scopes": [],
        "repos": [],
        "repo_count": None,
        "repos_private": None,
        "last_push": None,
        "error": None,
        "ms": 0,
        "source": "gh CLI (salt okunur)",
    }
    if not enabled:
        st["error"] = "config: github.enabled=false"
        return st
    if not st["binary"]:
        st["error"] = "gh bulunamadi"
        return st

    t0 = time.perf_counter()
    r = _run(["auth", "status"], timeout)
    if r["ok"] or r["out"]:
        parsed = _parse_auth_status(r["out"] + "\n" + r["err"])
        st.update({k: parsed[k] for k in ("authenticated", "account", "host", "protocol", "scopes")})
    if not r["ok"]:
        st["error"] = (r["err"] or "gh auth status hata")[:200]

    r = _run(["api", "user"], timeout)
    if r["ok"] and r["out"]:
        try:
            u = json.loads(r["out"])
            st["account"] = u.get("login") or st["account"]
            st["name"] = u.get("name") or None
            st["profile_url"] = u.get("html_url") or None
            st["authenticated"] = True
        except Exception:
            st["error"] = st["error"] or "gh api user cikisi ayristirilamadi"

    limit = int(gcfg.get("repos_limit", 15))
    owner = st.get("account")
    if owner:
        r = _run(
            [
                "repo", "list", owner,
                "--limit", str(limit),
                "--json", "nameWithOwner,visibility,pushedAt,isPrivate,isFork",
            ],
            timeout,
        )
        if r["ok"] and r["out"]:
            try:
                rows = json.loads(r["out"])
                st["repo_count"] = len(rows)
                st["repos_private"] = len([x for x in rows if x.get("isPrivate")])
                st["repos"] = [
                    {
                        "name": x.get("nameWithOwner"),
                        "visibility": x.get("visibility"),
                        "pushed_at": x.get("pushedAt"),
                        "private": bool(x.get("isPrivate")),
                        "fork": bool(x.get("isFork")),
                    }
                    for x in rows
                ]
                pushes = [x["pushed_at"] for x in st["repos"] if x.get("pushed_at")]
                st["last_push"] = max(pushes) if pushes else None
            except Exception:
                st["error"] = st["error"] or "gh repo list cikisi ayristirilamadi"
        else:
            st["error"] = st["error"] or (r["err"] or "gh repo list hata")[:200]
    st["ms"] = int((time.perf_counter() - t0) * 1000)
    return st
