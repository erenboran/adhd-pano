"""ADHD panosu — SQLite katmani (fikirler, gorevler, 'su an' tek gorevi, odak oturumu).

Fikir kaydi iki yere yazilir: SQLite (data/adhd.db) ve insan-okur dosya
(data/fikirler.md). Ayni satir DB'de md_line olarak saklanir; boylece test
kaydi silinebilir ve dosyadan da temizlenir.

Gorev alanlari (ADHD arastirmasindan turetilenler, hepsi istege bagli):
    first_step    ilk fiziksel adim — baslatmayi kirar (baslatma arizasi)
    cue           "eger-then" uyari — prospective memory, en guclu kanit
    estimate_min  tahmini sure — zaman koprlugu
    started_at    baslatildigi an — gecen sureyi gosterir
    due_at        son tarih — acilyet (ilgi-temelli sinir sistemi)
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'panel',
    md_line     TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    project     TEXT,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    done_at     TEXT
);
CREATE TABLE IF NOT EXISTS now_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    text        TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS focus (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    task_id     INTEGER,
    task_text   TEXT,
    minutes     INTEGER,
    started_at  TEXT,
    ends_at     TEXT,
    finished_at TEXT
);
"""

# mevcut tasks tablosuna eklenecek alanlar (kurulum oncesi/sonrasi fark etmez)
TASK_COLUMNS: dict[str, str] = {
    "first_step": "TEXT",
    "cue": "TEXT",
    "estimate_min": "INTEGER",
    "started_at": "TEXT",
    "due_at": "TEXT",
}

# update_task ile degistirilebilir alanlar
TASK_EDITABLE = {"text", "project", "first_step", "cue", "estimate_min", "due_at"}

MD_HEADER = "# Fikirler — ADHD panosu hizli kayit\n\nBu dosyaya panel üzerinden (klavyeden `i`)\neklenen fikirler satir satir yazilir. Bicim: `- [YYYY-AA-GG SS:DD] metin`\n\n"


class Store:
    def __init__(self, db_path: str, md_path: str):
        self.db_path = db_path
        self.md_path = md_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init()

    # ------------------------------------------------------------ helpers
    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)
            self._migrate(c)
        if not os.path.exists(self.md_path):
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write(MD_HEADER)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """var olan tabloya eksik kolonlari ekler (tekrar calistirmak guvenli)."""
        have = {r["name"] for r in c.execute("PRAGMA table_info(tasks)")}
        for col, typ in TASK_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typ}")

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _day(d: datetime | None = None) -> str:
        return (d or datetime.now().astimezone()).strftime("%Y-%m-%d")

    def _append_md(self, line: str) -> None:
        with open(self.md_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _remove_md(self, line: str) -> None:
        if not os.path.exists(self.md_path):
            return
        with open(self.md_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        out = [l for l in lines if l.rstrip("\n") != line]
        if len(out) != len(lines):
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.writelines(out)

    # -------------------------------------------------------------- ideas
    def add_idea(self, text: str, source: str = "panel") -> dict:
        text = " ".join(text.split())
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        md_line = f"- [{stamp}] {text}"
        with self._lock:
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO ideas (text, created_at, source, md_line) VALUES (?,?,?,?)",
                    (text, self._now(), source, md_line),
                )
                idea_id = cur.lastrowid
            self._append_md(md_line)
        return {"id": idea_id, "text": text, "created_at": self._now(), "source": source, "md_line": md_line}

    def list_ideas(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, text, created_at, source, md_line FROM ideas ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def idea_count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM ideas").fetchone()[0]

    def delete_idea(self, idea_id: int) -> bool:
        with self._lock:
            with self._conn() as c:
                row = c.execute("SELECT md_line FROM ideas WHERE id=?", (idea_id,)).fetchone()
                if not row:
                    return False
                c.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
            if row["md_line"]:
                self._remove_md(row["md_line"])
        return True

    # -------------------------------------------------------------- tasks
    def add_task(
        self,
        text: str,
        project: str | None = None,
        first_step: str | None = None,
        cue: str | None = None,
        estimate_min: int | None = None,
        due_at: str | None = None,
    ) -> dict:
        text = " ".join(text.split())
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO tasks (text, project, done, created_at, first_step, cue, estimate_min, due_at) "
                "VALUES (?,?,0,?,?,?,?,?)",
                (text, project or None, self._now(), first_step, cue, estimate_min, due_at),
            )
            tid = cur.lastrowid
        return {
            "id": tid, "text": text, "project": project or None, "done": 0,
            "first_step": first_step, "cue": cue, "estimate_min": estimate_min,
            "due_at": due_at, "started_at": None,
        }

    def list_tasks(self) -> list[dict]:
        cols = "id, text, project, done, created_at, done_at, " + ", ".join(TASK_COLUMNS)
        with self._conn() as c:
            rows = c.execute(
                f"SELECT {cols} FROM tasks ORDER BY done ASC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        cols = "id, text, project, done, created_at, done_at, " + ", ".join(TASK_COLUMNS)
        with self._conn() as c:
            row = c.execute(f"SELECT {cols} FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: int, fields: dict) -> dict | None:
        """yalnizca TASK_EDITABLE alanlarina izin verilir; deger None ise silinir."""
        sets, vals = [], []
        for k, v in fields.items():
            if k not in TASK_EDITABLE:
                continue
            if k in ("first_step", "cue", "project", "text") and isinstance(v, str):
                v = " ".join(v.split()) or None
            if k == "estimate_min":
                v = int(v) if v not in (None, "") else None
            if k == "due_at" and isinstance(v, str) and not v.strip():
                v = None
            sets.append(f"{k}=?")
            vals.append(v)
        if not sets:
            return self.get_task(task_id)
        vals.append(task_id)
        with self._conn() as c:
            cur = c.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
            if cur.rowcount == 0:
                return None
        return self.get_task(task_id)

    def set_started(self, task_id: int, on: bool) -> dict | None:
        """gorev 'baslatildi' isareti — gecen sureyi gosterir (zaman koprlugu)."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE tasks SET started_at=? WHERE id=?",
                (self._now() if on else None, task_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_task(task_id)

    def toggle_task(self, task_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT id, done FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            done = 0 if row["done"] else 1
            c.execute(
                "UPDATE tasks SET done=?, done_at=? WHERE id=?",
                (done, self._now() if done else None, task_id),
            )
        return {"id": task_id, "done": done}

    def delete_task(self, task_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            return cur.rowcount > 0

    # ------------------------------------------------- seri (streak / ani odul)
    def streak(self) -> dict:
        """art arda kac gundur en az 1 gorev bitirildigi (bugun ya da dunden baslar).

        ADHD icin onemi: ani, gorunur odul; seri kirilmasi gorsel geri bildirim.
        """
        with self._conn() as c:
            days = {r["d"] for r in c.execute(
                "SELECT DISTINCT substr(done_at,1,10) AS d FROM tasks "
                "WHERE done=1 AND done_at IS NOT NULL"
            ).fetchall()}
            today_done = c.execute(
                "SELECT COUNT(*) FROM tasks WHERE done=1 AND substr(done_at,1,10)=?",
                (self._day(),),
            ).fetchone()[0]
            total_done = c.execute("SELECT COUNT(*) FROM tasks WHERE done=1").fetchone()[0]

        today = datetime.now().astimezone()
        # bugun hic bitis yoksa seri dunden devam ediyor sayilir (kirilmadi)
        cursor = today if self._day(today) in days else today - timedelta(days=1)
        n = 0
        while self._day(cursor) in days:
            n += 1
            cursor -= timedelta(days=1)
        return {
            "streak": n,
            "today_done": today_done,
            "total_done": total_done,
            "today": self._day(today),
            "active_today": today_done > 0,
        }

    # ------------------------------------------------------- odak oturumu
    def focus_start(self, task_id: int | None, task_text: str | None, minutes: int) -> dict:
        now = datetime.now().astimezone()
        ends = now + timedelta(minutes=minutes)
        with self._conn() as c:
            c.execute(
                "INSERT INTO focus (id, task_id, task_text, minutes, started_at, ends_at, finished_at) "
                "VALUES (1,?,?,?,?,?,NULL) "
                "ON CONFLICT(id) DO UPDATE SET task_id=excluded.task_id, task_text=excluded.task_text, "
                "minutes=excluded.minutes, started_at=excluded.started_at, ends_at=excluded.ends_at, "
                "finished_at=NULL",
                (task_id, task_text, minutes,
                 now.isoformat(timespec="seconds"), ends.isoformat(timespec="seconds")),
            )
        return self.focus_state()

    def focus_stop(self) -> dict:
        """oturumu kapatir (sure doldugunda ekranda hatirlatilir, kapatilinca biter)."""
        with self._conn() as c:
            c.execute("DELETE FROM focus WHERE id=1")
        return self.focus_state()

    def focus_state(self) -> dict:
        """aktif / bitmis oturum durumu.

        Sure doldugunda satir silinmez; finished_at isaretlenir ve kullanici
        onaylayana dek ekranda kalir (dis saldirgan — baktiginda gorursun).
        """
        with self._conn() as c:
            row = c.execute(
                "SELECT task_id, task_text, minutes, started_at, ends_at, finished_at "
                "FROM focus WHERE id=1"
            ).fetchone()
        if not row:
            return {"active": False, "finished": False, "remaining_sec": 0}

        base = {
            "task_id": row["task_id"], "task_text": row["task_text"],
            "minutes": row["minutes"], "started_at": row["started_at"],
            "ends_at": row["ends_at"],
        }
        if row["finished_at"]:
            return dict(base, active=False, finished=True, remaining_sec=0)

        try:
            ends = datetime.fromisoformat(row["ends_at"])
        except (TypeError, ValueError):
            return {"active": False, "finished": False, "remaining_sec": 0}

        remaining = int((ends - datetime.now().astimezone()).total_seconds())
        if remaining <= 0:
            with self._lock:
                with self._conn() as c:
                    c.execute("UPDATE focus SET finished_at=? WHERE id=1", (self._now(),))
            return dict(base, active=False, finished=True, remaining_sec=0)
        return dict(base, active=True, finished=False, remaining_sec=remaining)

    # ---------------------------------------------------------------- now
    def get_now(self) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT text, updated_at FROM now_state WHERE id=1").fetchone()
        if not row:
            return {"text": None, "updated_at": None}
        return {"text": row["text"], "updated_at": row["updated_at"]}

    def set_now(self, text: str | None) -> dict:
        text = " ".join((text or "").split()) or None
        with self._conn() as c:
            c.execute(
                "INSERT INTO now_state (id, text, updated_at) VALUES (1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET text=excluded.text, updated_at=excluded.updated_at",
                (text, self._now()),
            )
        return self.get_now()
