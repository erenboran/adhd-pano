#!/usr/bin/env python
"""ADHD panosu — uctan uca duman testi (gercek HTTP, gercek repo'lar, gercek gh).

Kullanim:  python D:/ADHD/tools/smoke_test.py [port]
Varsayilan port 5078'tir; boylece calisan 5077 panosu ile catismaz.
Test, GECICI bir test fikri ekler ve sonunda hem DB'den hem data/fikirler.md'den siler.
Harici kutuphane gerektirmez (Flask/werkzeug yok — app.py ile ayni stdlib sunucu).
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import app as adhd  # noqa: E402
import scanner  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5078
B = f"http://127.0.0.1:{PORT}"
FAILS: list[str] = []


def call(path: str, data=None, method: str | None = None) -> tuple[float, dict, int]:
    t = time.perf_counter()
    req = urllib.request.Request(B + path, method=method or ("POST" if data is not None else "GET"))
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body, code = r.read(), r.status
    except urllib.error.HTTPError as e:  # 4xx beklenen durumlar icin
        body, code = e.read(), e.code
    return round((time.perf_counter() - t) * 1000, 1), json.loads(body), code


def raw(path: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(B + path, timeout=30) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def main() -> int:
    cfg = adhd.load_config()
    cfg["port"] = PORT
    adhd_app = adhd.App(cfg)
    srv = adhd.make_http_server(adhd_app, "127.0.0.1", PORT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"=== test sunucusu: {B} (config: git_timeout={cfg['git_timeout_sec']}s ttl={cfg['cache_ttl_sec']}s) ===")
    print(f"    python {sys.version.split()[0]} | pywebview: {adhd.pywebview_installed()} "
          f"| WebView2: {adhd.webview2_available()}")

    try:
        # ---------------------------------------------------- 0) STATIK + GUVENLIK
        print("\n0) STATIK DOSYALAR + GUVENLIK")
        code, ctype, body = raw("/static/app.css")
        check("statik css dondu", code == 200 and b"--bg" in body, f"{code} {ctype}")
        code, ctype, body = raw("/")
        check("ana sayfa dondu", code == 200 and b"<title>" in body, f"{code}")
        code, _, _ = raw("/static/../app.py")
        check("path traversal engellendi (404)", code == 404, f"HTTP {code}")
        _, j404, code404 = call("/api/yok-boyle-bir-sey")
        check("bilinmeyen uc 404 dondurur", code404 == 404 and j404.get("ok") is False)
        _, _, code405 = call("/api/health", {}, method="DELETE")
        check("yanlis yontem 405 dondurur", code405 == 405, f"HTTP {code405}")

        # ---------------------------------------------------- 1) SOGUK BASLANGIC
        print("\n1) SOGUK BASLANGIC — tarama surerken pano donuyor mu?")
        cold = []
        for _ in range(3):
            ms, d, code = call("/api/state")
            cold.append((ms, d.get("ready"), d.get("refreshing")))
            time.sleep(0.2)
        print(f"   ilk 3 cagri (ms | ready | refreshing): {cold}")
        check("soguk cagrilar 1 sn altinda dondu (donma yok)", all(ms < 1000 for ms, _, _ in cold),
              f"en yavas {max(ms for ms, _, _ in cold)} ms")
        check("ilk cagri HTTP 200", code == 200)

        t0 = time.time()
        while True:
            ms, d, code = call("/api/state")
            if d.get("ready"):
                break
            if time.time() - t0 > 90:
                raise SystemExit("tarama 90 sn'de bitmedi")
            time.sleep(0.25)
        ready_sec = round(time.time() - t0, 2)
        s = d["scan"]
        print(f"   hazir olma: {ready_sec} sn | tarama (duvar) {s.get('wall_sec')}s "
              f"(git {s.get('duration_sec')}s, kesif {s.get('discovery_sec')}s, {s.get('dirs_visited')} klasor)")
        print(f"   repo: {s.get('repos_scanned')} tarandi / {s.get('repos_discovered')} kesfedildi"
              f" | git deposu: {s.get('git_repos')} | timeout: {s.get('timeout_count')} {s.get('timeouts')}")
        check("tarama gercek repo dondurdu", (s.get("repos_scanned") or 0) > 0, f"{s.get('repos_scanned')} repo")
        check("timeout listesi raporlanmis", isinstance(s.get("timeouts"), list))

        projetos = d["projects"]
        with_branch = [p for p in projetos if p.get("branch")]
        with_date = [p for p in projetos if p.get("last_commit_iso")]
        print(f"   projeler: {len(projetos)} | branch okunan: {len(with_branch)} | son commit tarihi okunan: {len(with_date)}")
        for p in projetos[:5]:
            print(f"     - {p['name']:<20} br={p['branch']} dirty={p['dirty']} son={p['last_commit_iso']} 7g={p['commits_7d']}")
        check("gercek branch adlari geldi", len(with_branch) >= 5, f"{len(with_branch)} proje")
        check("gercek commit tarihleri geldi", len(with_date) >= 5, f"{len(with_date)} proje")
        check("bilinmeyen alanlar None (0 uydurma yok)",
              all(p["dirty"] is None or isinstance(p["dirty"], int) for p in projetos))
        check("yapilanlar (son 7 gun) dolu", len(d["yapilanlar"]) > 0, f"{len(d['yapilanlar'])} commit")
        check("uyelikler.json okundu", d["uyelikler"].get("ok") is True)

        g = d["github"]
        print(f"   gh: {g.get('account')} ({g.get('name')}) auth={g.get('authenticated')} "
              f"host={g.get('host')} scopes={g.get('scopes')} repo={g.get('repo_count')} son_push={g.get('last_push')}")
        check("gh hesabi gercek", bool(g.get("account")) and g.get("account") != ".login", str(g.get("account")))
        check("gh repo listesi gercek", (g.get("repo_count") or 0) > 0, f"{g.get('repo_count')} repo")

        # ---------------------------------------------------- 2) CACHE DAVRANISI
        print("\n2) CACHE — 60 sn TTL, tekrar tarama yok")
        gen1 = d.get("scan_generated_at")
        times = []
        for _ in range(3):
            ms, d2, _ = call("/api/state")
            times.append(ms)
        time.sleep(1)
        ms, d3, _ = call("/api/state")
        print(f"   cache'li cagri sureleri (ms): {times} | son: {ms} ms | yas: {d3.get('cached_age_sec')} sn")
        check("cache'li cagrilar hizli (<200 ms)", all(t < 200 for t in times + [ms]), f"max {max(times + [ms])} ms")
        check("TTL icinde yeniden tarama yok", d3.get("scan_generated_at") == gen1, f"generated_at sabit: {gen1}")
        check("cache yasi TTL'in altinda", (d3.get("cached_age_sec") or 999) < cfg["cache_ttl_sec"])

        # ---------------------------------------------------- 3) ZORLA YENILEME
        print("\n3) ZORLA YENILEME — tarama surerken de donmuyor")
        call("/api/refresh", {}, method="POST")
        ms, d4, _ = call("/api/state")
        print(f"   yenileme surerken cagri: {ms} ms | ready={d4.get('ready')} refreshing={d4.get('refreshing')}")
        check("yenileme surerken cagri hizli dondu (<1000 ms)", ms < 1000, f"{ms} ms")
        for _ in range(60):
            _, d5, _ = call("/api/state")
            if not d5.get("refreshing") and d5.get("scan_generated_at") != gen1:
                break
            time.sleep(0.5)
        print(f"   yeni tarama: {d5['scan'].get('wall_sec')}s | timeout {d5['scan'].get('timeout_count')}"
              f" | generated_at {d5.get('scan_generated_at')}")
        check("zorla yenileme yeni tarama uretti", d5.get("scan_generated_at") != gen1)

        # ---------------------------------------------------- 4) FIKIR / GOREV / SU AN
        print("\n4) FIKIR KAYDI — data/fikirler.md + SQLite + data/pano.md (Hermes export)")
        marker = f"smoke test fikri {int(time.time())}"
        ms, res, code = call("/api/ideas", {"text": marker})
        check("fikir eklendi (HTTP 200)", code == 200 and res.get("ok"), str(res.get("error")))
        idea_id = res["idea"]["id"]
        md_path = BASE / "data" / "fikirler.md"
        md_text = md_path.read_text(encoding="utf-8")
        check("fikir data/fikirler.md'ye yazildi", marker in md_text, str(md_path))
        pano = BASE / "data" / "pano.md"
        check("data/pano.md (Hermes ozeti) olustu", pano.exists() and marker in pano.read_text(encoding="utf-8"),
              str(pano))
        _, st, _ = call("/api/state")
        check("fikir DB'den listeleniyor", any(i["text"] == marker for i in st["ideas"]), f"idea_count={st['idea_count']}")
        dms, _, dcode = call(f"/api/ideas/{idea_id}", method="DELETE")
        _, st2, _ = call("/api/state")
        check("test kaydi DB'den silindi", not any(i["id"] == idea_id for i in st2["ideas"]))
        check("test kaydi .md'den de silindi", marker not in md_path.read_text(encoding="utf-8"))
        check("test kaydi pano.md'den de silindi", marker not in pano.read_text(encoding="utf-8"))
        _, _, bad = call("/api/ideas", {"text": "   "})
        check("bos fikir reddedildi (400)", bad == 400, f"HTTP {bad}")

        print("\n5) GOREV + SU AN")
        _, t1, _ = call("/api/tasks", {"text": "smoke test gorevi", "project": "ADHD"})
        tid = t1["task"]["id"]
        check("gorev proje etiketiyle eklendi", t1["task"].get("project") == "ADHD", str(t1["task"]))
        _, tt, _ = call(f"/api/tasks/{tid}/toggle", {}, method="POST")
        check("gorev eklendi + isaretlendi", tt["task"]["done"] == 1)
        status, ctype, export_body = raw("/api/export")
        check("/api/export markdown dondurur", status == 200 and "markdown" in ctype and b"## SU AN" in export_body,
              f"{status} {ctype}")
        check("export'ta gorev gorunuyor", b"smoke test gorevi" in export_body)
        call(f"/api/tasks/{tid}", method="DELETE")
        _, n1, _ = call("/api/now", {"text": "smoke test"})
        check("su an guncellendi", n1["now"]["text"] == "smoke test")
        call("/api/now", {"text": ""})
        _, d6, _ = call("/api/state")
        check("su an temizlendi", d6["now"]["text"] is None)

        # ---------------------------------------------------- 6) TIMEOUT YOLU
        print("\n6) TIMEOUT YOLU — okunamayan alan 'bilinmiyor' kalir mi?")
        import copy
        c2 = copy.deepcopy(cfg)
        c2["git_timeout_sec"] = 0.0005
        snap = scanner.build_snapshot(c2, scanner.DiscoveryCache(0))
        p = snap["projects"][0]
        print(f"   timeout_count={snap['scan']['timeout_count']} ornek: {p['name']} branch={p['branch']} "
              f"dirty={p['dirty']} 7g={p['commits_7d']} timeout={p['timeout']}")
        check("timeout sayisi > 0", snap["scan"]["timeout_count"] > 0)
        check("timeout'ta alanlar None kaldi (0 uydurma yok)",
              all(m["branch"] is None and m["dirty"] is None for m in snap["projects"] if m["timeout"]))

        # ---------------------------------------------------- 7) DIS BAGIMLILIK
        print("\n7) DIS BAGIMLILIK — CDN/internet referansi var mi?")
        files = ["templates/index.html", "static/app.js", "static/app.css"]
        # Kaynak YUKLEYEN referanslar yasak. (app.js'deki ghUrl() sadece repo linki
        # uretir; kullanici tiklayinca tarayici acar — sayfa kendi basina istek atmaz.)
        patterns = (
            'src="http', "src='http", 'href="http', "href='http", "@import", "url(http",
            "fonts.googleapis", "fonts.gstatic", "cdn.", "unpkg", "jsdelivr", "//cdnjs",
            "cdnjs.cloudflare", "googleapis.com",
        )
        bad_refs = []
        for f in files:
            text = (BASE / f).read_text(encoding="utf-8")
            for pat in patterns:
                if pat in text:
                    bad_refs.append(f"{f}: {pat}")
        check("html/css/js kaynak yukleyen dis referans yok", not bad_refs, "; ".join(bad_refs))
        js = (BASE / "static" / "app.js").read_text(encoding="utf-8")
        check("JS fetch cagrilari yalnizca yerel /api yollarina",
              js.count("fetch(") == 1 and "fetch(path" in js)
        py = "\n".join(
            (BASE / f).read_text(encoding="utf-8")
            for f in ("app.py", "db.py", "scanner.py", "ghclient.py")
        )
        check("pip/yabanci modul importu yok (Flask, requests, pywebview zorunlu degil)",
              all(x not in py for x in ("import flask", "from flask", "import requests", "import bottle")))

        # ---------------------------------------------------- 8) MASAUSTU PENCERE
        print("\n8) MASAUSTU PENCERE HAZIRLIGI")
        print(f"    pywebview kurulu: {adhd.pywebview_installed()} | WebView2 runtime: {adhd.webview2_available()}")
        check("pencere icin WebView2 runtime mevcut", adhd.webview2_available(),
              "yoksa app.py otomatik tarayiciya duser")
        check("pywebview kuruldu (kurulu degilse tarayici moduna duser)", adhd.pywebview_installed(),
              "kurulum: D:/ADHD/setup.cmd")

        # ---------------------------------------------------- 9) ADHD OZELLIKLERI
        print("\n9) ADHD OZELLIKLERI — zaman gorunurlugu, ilk adim, uyari, odak, seri")
        # (P1) arayuzde canli saat + gun ilerlemesi var mi?
        _, _, html_b = raw("/")
        html_txt = html_b.decode("utf-8", "replace")
        check("arayuzde canli saat kutusu var", 'id="clock-time"' in html_txt)
        check("arayuzde gun ilerleme cubugu var", 'id="daybar-fill"' in html_txt)
        check("arayuzde odak kutusu var", 'id="focus-box"' in html_txt)
        js_b = (BASE / "static" / "app.js").read_text(encoding="utf-8")
        check("JS saniyelik tick() dongusu var", "setInterval(tick, 1000)" in js_b)

        # (P2+P3+P6) gorev alanlari: ilk adim / uyari / tahmin / son tarih
        _, t2, _ = call("/api/tasks", {
            "text": "adhd ozellik testi", "project": "ADHD",
            "first_step": "bos docx'i ac", "cue": "ogle yemegi bitince",
            "estimate_min": 25, "due_at": "2026-09-28T18:00",
        })
        tk = t2.get("task") or {}
        tid2 = tk.get("id")
        check("gorev 4 ADHD alaniyla eklendi",
              tk.get("first_step") == "bos docx'i ac" and tk.get("cue") == "ogle yemegi bitince"
              and tk.get("estimate_min") == 25 and tk.get("due_at") == "2026-09-28T18:00",
              str(tk))
        _, up, upc = call(f"/api/tasks/{tid2}/update", {"first_step": "yeni ilk adim", "estimate_min": None})
        check("gorev alani guncellendi (None = temizle)", upc == 200
              and up["task"]["first_step"] == "yeni ilk adim" and up["task"]["estimate_min"] is None)
        _, up2, upc2 = call(f"/api/tasks/{tid2}/update", {"estimate_min": 9999})
        check("tahmin sinir disi reddedilir/None yapildi",
              upc2 == 200 and up2["task"]["estimate_min"] is None, str(up2["task"]))

        # (P1) baslatma → gecen sure
        _, st1, _ = call(f"/api/tasks/{tid2}/start", {"on": True}, method="POST")
        check("gorev baslatildi (started_at dolu)", bool(st1["task"].get("started_at")),
              str(st1["task"].get("started_at")))
        _, st2, _ = call(f"/api/tasks/{tid2}/start", {"on": False}, method="POST")
        check("gorev duraklatildi (started_at None)", st2["task"].get("started_at") is None)

        # (P4) odak oturumu
        _, f1, _ = call("/api/focus/start", {"minutes": 25, "task_id": tid2})
        foc = f1.get("focus") or {}
        check("odak oturumu basladi", foc.get("active") is True and 0 < (foc.get("remaining_sec") or 0) <= 1500,
              f"{foc.get('remaining_sec')} sn")
        check("odak gorev metnini aldi", foc.get("task_text") == "adhd ozellik testi", str(foc.get("task_text")))
        _, st3, _ = call("/api/state")
        check("state odak + seri dondurur", isinstance(st3.get("focus"), dict) and isinstance(st3.get("streak"), dict),
              f"focus={st3.get('focus', {}).get('active')} streak={st3.get('streak', {}).get('streak')}")
        open_tasks = st3.get("tasks") or []
        check("state gorevlerde yeni alanlar var",
              all(k in open_tasks[0] for k in ("first_step", "cue", "estimate_min", "started_at", "due_at")),
              ", ".join(open_tasks[0].keys()) if open_tasks else "gorev yok")
        _, f2, _ = call("/api/focus/stop", {}, method="POST")
        check("odak kapatildi", f2["focus"].get("active") is False)

        # (P5) seri
        check("seri verisi anlamlı", st3["streak"].get("streak", -1) >= 0
              and isinstance(st3["streak"].get("today_done"), int), str(st3["streak"]))

        # export'a yeni alanlar yansidi mi?
        _, _, exp2 = raw("/api/export")
        exp_txt = exp2.decode("utf-8", "replace")
        check("export'ta 'Odak / seri' bolumu var", "## Odak / seri" in exp_txt)
        check("export'ta gorev bayraklari var", "ilk adim:" in exp_txt,
              "yok" if "ilk adim:" not in exp_txt else "var")

        # hatali girisler
        _, _, c_b = call("/api/tasks", {"text": "x" * 400})
        check("400 karakter ustu gorev reddedildi", c_b == 400, f"HTTP {c_b}")
        _, _, c_404 = call("/api/focus/start", {"minutes": 25, "task_id": 999999})
        check("olmayan gorevle odak 404", c_404 == 404, f"HTTP {c_404}")
        _, _, c_upd = call("/api/tasks/999999/update", {"first_step": "yok"})
        check("olmayan gorev guncelleme 404", c_upd == 404, f"HTTP {c_upd}")

        # temizlik — test verisi geride kalmasin
        call("/api/focus/stop", {}, method="POST")
        call(f"/api/tasks/{tid2}", method="DELETE")
        _, st4, _ = call("/api/state")
        check("test görevi silindi", not any(t["text"] == "adhd ozellik testi" for t in st4["tasks"]))
    finally:
        srv.shutdown()
        srv.server_close()

    print("\n=== SONUC:", "TUM TESTLER GECTI" if not FAILS else f"{len(FAILS)} BASARISIZ: {FAILS}", "===")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
