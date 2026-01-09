from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

def _resolve_schema_file() -> Path:
    candidates = [
        Path(__file__).with_name("schema.sql"),
        Path.cwd() / "schema.sql",
    ]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates.append(Path(base) / "schema.sql")
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


SCHEMA_FILE = _resolve_schema_file()


def _normalize_actor_record(record: Mapping[str, object]) -> Optional[Tuple[str, str]]:
    raw_name = (
        record.get("actor_name")
        or record.get("name")
        or record.get("strong")
        or record.get("title")
        or ""
    )
    raw_href = record.get("href") or record.get("url") or ""
    name = str(raw_name).strip()
    href = str(raw_href).strip()
    return (name, href) if name else None


def _normalize_work_record(
    record: Mapping[str, object]
) -> Optional[Tuple[str, str, str]]:
    code = str(record.get("code") or "").strip()
    href = str(record.get("href") or "").strip()
    title = record.get("title")
    title_str = str(title).strip() if title is not None else ""
    if not code or not href:
        return None
    return code, href, title_str


def _normalize_magnet_record(
    record: Mapping[str, object]
) -> Optional[Tuple[str, str, str]]:
    magnet = str(record.get("href") or record.get("magnet") or "").strip()
    if not magnet:
        return None
    tags_field = record.get("tags") or record.get("tag") or ""
    if isinstance(tags_field, (list, tuple, set)):
        tags = ", ".join(str(item).strip() for item in tags_field if item)
    else:
        tags = str(tags_field).strip()
    size = str(record.get("size") or "").strip()
    return magnet, tags, size


class Storage(AbstractContextManager["Storage"]):
    """
    基于 sqlite3 的轻量级工具类，用于存储抓取的数据。
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> "Storage":
        self.open()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if not self._conn:
            return
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("数据库连接尚未打开")
        return self._conn

    def open(self) -> None:
        if self._conn:
            return
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        assert self._conn is not None
        if not SCHEMA_FILE.exists():
            raise FileNotFoundError(f"未找到数据库结构定义文件: {SCHEMA_FILE}")
        schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)

    # --- 演员相关工具 -------------------------------------------------

    def save_actors(self, actors: Iterable[Mapping[str, object]]) -> int:
        valid_rows: List[Tuple[str, str]] = []
        for actor in actors:
            normalized = _normalize_actor_record(actor)
            if normalized:
                valid_rows.append(normalized)
        if not valid_rows:
            return 0

        with self.conn:
            for name, href in valid_rows:
                self.conn.execute(
                    """
                    INSERT INTO actors (name, href)
                    VALUES (?, ?)
                    ON CONFLICT(name) DO UPDATE SET href=excluded.href
                    """,
                    (name, href),
                )
        return len(valid_rows)

    def iter_actor_urls(self) -> List[Tuple[str, str]]:
        cur = self.conn.execute(
            "SELECT name, COALESCE(href, '') AS href "
            "FROM actors ORDER BY LOWER(name)"
        )
        return [(row["name"], row["href"]) for row in cur]

    def _ensure_actor(self, name: str, href: str | None = None) -> int:
        row = self.conn.execute(
            "SELECT id FROM actors WHERE name = ?", (name,)
        ).fetchone()
        if row:
            if href:
                self.conn.execute(
                    "UPDATE actors SET href = ? WHERE id = ? AND COALESCE(href, '') != ?",
                    (href, row["id"], href),
                )
            return int(row["id"])
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO actors (name, href) VALUES (?, ?)", (name, href)
            )
        return int(cursor.lastrowid)

    # --- 作品相关工具 --------------------------------------------------

    def save_actor_works(
        self,
        actor_name: str,
        actor_href: str,
        works: Iterable[Mapping[str, object]],
    ) -> int:
        normalized: List[Tuple[str, str, str]] = []
        for work in works:
            entry = _normalize_work_record(work)
            if entry:
                normalized.append(entry)
        if not normalized:
            return 0

        actor_id = self._ensure_actor(actor_name, actor_href)
        with self.conn:
            for code, href, title in normalized:
                self.conn.execute(
                    """
                    INSERT INTO works (actor_id, code, title, href)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(actor_id, code) DO UPDATE SET
                        title = excluded.title,
                        href = excluded.href
                    """,
                    (actor_id, code, title or None, href or None),
                )
        return len(normalized)

    def get_actor_works(self, actor_name: str) -> List[Dict[str, str]]:
        cur = self.conn.execute(
            """
            SELECT w.code, COALESCE(w.title, '') AS title, COALESCE(w.href, '') AS href
            FROM works w
            JOIN actors a ON a.id = w.actor_id
            WHERE a.name = ?
            ORDER BY w.code
            """,
            (actor_name,),
        )
        return [
            {"code": row["code"], "title": row["title"], "href": row["href"]}
            for row in cur
        ]

    def get_all_actor_works(self) -> Dict[str, List[Dict[str, str]]]:
        cur = self.conn.execute(
            """
            SELECT a.name AS actor_name,
                   COALESCE(a.href, '') AS actor_href,
                   w.code,
                   COALESCE(w.title, '') AS title,
                   COALESCE(w.href, '') AS href
            FROM works w
            JOIN actors a ON a.id = w.actor_id
            ORDER BY LOWER(a.name), w.code
            """
        )
        grouped: Dict[str, List[Dict[str, str]]] = {}
        for row in cur:
            grouped.setdefault(row["actor_name"], []).append(
                {"code": row["code"], "title": row["title"], "href": row["href"]}
            )
        return grouped

    def _ensure_work(
        self,
        actor_name: str,
        actor_href: str,
        code: str,
        title: str | None,
        href: str | None,
    ) -> int:
        actor_id = self._ensure_actor(actor_name, actor_href)
        row = self.conn.execute(
            """
            SELECT id FROM works
            WHERE actor_id = ? AND code = ?
            """,
            (actor_id, code),
        ).fetchone()
        if row:
            return int(row["id"])
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO works (actor_id, code, title, href)
                VALUES (?, ?, ?, ?)
                """,
                (actor_id, code, title or None, href or None),
            )
        return int(cursor.lastrowid)

    # --- 磁链相关工具 --------------------------------------------------

    def save_magnets(
        self,
        actor_name: str,
        actor_href: str,
        code: str,
        magnets: Iterable[Mapping[str, object]],
        *,
        title: str | None = None,
        href: str | None = None,
    ) -> int:
        normalized: List[Tuple[str, str, str]] = []
        for magnet in magnets:
            entry = _normalize_magnet_record(magnet)
            if entry:
                normalized.append(entry)

        work_id = self._ensure_work(actor_name, actor_href, code, title, href)
        with self.conn:
            self.conn.execute("DELETE FROM magnets WHERE work_id = ?", (work_id,))
            if normalized:
                self.conn.executemany(
                    """
                    INSERT INTO magnets (work_id, magnet, tags, size)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (work_id, magnet, tags or None, size or None)
                        for magnet, tags, size in normalized
                    ],
                )
        return len(normalized)

    def get_magnets_grouped(self) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
        cur = self.conn.execute(
            """
            SELECT
                a.name AS actor_name,
                COALESCE(a.href, '') AS actor_href,
                w.code,
                COALESCE(w.title, '') AS title,
                COALESCE(w.href, '') AS href,
                m.magnet,
                COALESCE(m.tags, '') AS tags,
                COALESCE(m.size, '') AS size
            FROM magnets m
            JOIN works w ON w.id = m.work_id
            JOIN actors a ON a.id = w.actor_id
            ORDER BY LOWER(a.name), w.code
            """
        )

        grouped: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        for row in cur:
            actor_bucket = grouped.setdefault(row["actor_name"], {})
            work_bucket = actor_bucket.setdefault(row["code"], [])
            work_bucket.append(
                {
                    "magnet": row["magnet"],
                    "tags": row["tags"],
                    "size": row["size"],
                    "title": row["title"],
                    "href": row["href"],
                }
            )
        return grouped

    def get_actor_href(self, actor_name: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT href FROM actors WHERE name = ?", (actor_name,)
        ).fetchone()
        return str(row["href"]) if row and row["href"] is not None else None
