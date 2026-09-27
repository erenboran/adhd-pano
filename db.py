"""ADHD panosu — SQLite katmani (fikirler, gorevler, 'su an' tek gorevi).

Fikir kaydi iki yere yazilir: SQLite (data/adhd.db) ve insan-okur dosya
(data/fikirler.md). Ayni satir DB'de md_line olarak saklanir; boylece test
kaydi silinebilir ve dosyadan da temizlenir.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime

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
"""

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
        if not os.path.exists(self.md_path):
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write(MD_HEADER)

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

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
    def add_task(self, text: str, project: str | None = None) -> dict:
        text = " ".join(text.split())
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO tasks (text, project, done, created_at) VALUES (?,?,0,?)",
                (text, project or None, self._now()),
            )
            tid = cur.lastrowid
        return {"id": tid, "text": text, "project": project or None, "done": 0}

    def list_tasks(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, text, project, done, created_at, done_at FROM tasks ORDER BY done ASC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

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
