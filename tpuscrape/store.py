"""SQLite state store + per-GPU file output + master index."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import yaml

from .config import Config


class Store:
    def __init__(self, config: Config):
        self.config = config
        self.state_dir: Path = config.path("state_dir")
        self.output_dir: Path = config.path("output_dir")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "scraper.db"
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gpus (
                    id         TEXT PRIMARY KEY,
                    name       TEXT,
                    url        TEXT,
                    slug       TEXT,
                    source     TEXT,
                    status     TEXT DEFAULT 'queued',
                    attempts   INTEGER DEFAULT 0,
                    error      TEXT,
                    scraped_at TEXT,
                    summary    TEXT
                )
                """
            )

    # -- records -------------------------------------------------------------
    def upsert_gpu(
        self,
        gpu_id: str,
        name: str,
        url: str,
        slug: str = "",
        source: str = "seed",
        summary: dict | None = None,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO gpus (id, name, url, slug, source, summary)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = COALESCE(excluded.name, gpus.name),
                    url  = COALESCE(excluded.url, gpus.url),
                    slug = COALESCE(excluded.slug, gpus.slug),
                    source = COALESCE(excluded.source, gpus.source)
                """,
                (
                    gpu_id,
                    name,
                    url,
                    slug,
                    source,
                    json.dumps(summary) if summary else None,
                ),
            )

    def set_status(
        self,
        gpu_id: str,
        status: str,
        error: str | None = None,
        scraped_at: str | None = None,
        summary: dict | None = None,
    ):
        with self._conn() as conn:
            if summary is not None:
                conn.execute(
                    "UPDATE gpus SET status=?, error=?, scraped_at=?, summary=? WHERE id=?",
                    (status, error, scraped_at, json.dumps(summary), gpu_id),
                )
            elif scraped_at is not None:
                conn.execute(
                    "UPDATE gpus SET status=?, error=?, scraped_at=? WHERE id=?",
                    (status, error, scraped_at, gpu_id),
                )
            else:
                conn.execute(
                    "UPDATE gpus SET status=?, error=? WHERE id=?", (status, error, gpu_id)
                )

    def bump_attempt(self, gpu_id: str) -> int:
        with self._conn() as conn:
            conn.execute("UPDATE gpus SET attempts = attempts + 1 WHERE id=?", (gpu_id,))
            row = conn.execute("SELECT attempts FROM gpus WHERE id=?", (gpu_id,)).fetchone()
            return row["attempts"] if row else 0

    def get(self, gpu_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM gpus WHERE id=?", (gpu_id,)).fetchone()
            return dict(row) if row else None

    def has(self, gpu_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM gpus WHERE id=?", (gpu_id,)).fetchone() is not None

    def list_by_status(self, status: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM gpus WHERE status=? ORDER BY name", (status,)
            ).fetchall()
            return [dict(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM gpus GROUP BY status").fetchall()
            return {r["status"]: r["n"] for r in rows}

    def all_ids(self) -> set[str]:
        with self._conn() as conn:
            return {r["id"] for r in conn.execute("SELECT id FROM gpus").fetchall()}

    def pending_count(self) -> int:
        return len(self.list_by_status("queued")) + len(self.list_by_status("blocked"))

    def random_pending(self) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM gpus WHERE status IN ('queued','blocked') ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    # -- output --------------------------------------------------------------
    def gpu_folder(self, slug: str) -> Path:
        folder = self.output_dir / (slug or "unknown")
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_raw_html(self, slug: str, html: str) -> Path:
        folder = self.gpu_folder(slug)
        path = folder / "page.html"
        path.write_text(html, encoding="utf-8")
        return path

    def write_spec(self, slug: str, data: dict) -> Path:
        folder = self.gpu_folder(slug)
        path = folder / "spec.yaml"
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                data,
                fh,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
                width=1000,
            )
        return path

    def write_index(self):
        """Write data/index.json as the aggregate master list."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM gpus WHERE status='done' ORDER BY name"
            ).fetchall()
        entries = []
        for r in rows:
            summary = json.loads(r["summary"]) if r["summary"] else {}
            entries.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "slug": r["slug"],
                    "url": r["url"],
                    "source": r["source"],
                    "scraped_at": r["scraped_at"],
                    "key_specs": summary,
                }
            )
        path = self.output_dir / "index.json"
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        return path, len(entries)
