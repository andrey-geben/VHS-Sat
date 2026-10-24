"""SQLite layer for VHS-Sat. Cross-platform."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import config


DB_PATH = Path(config.get("database", "path", default="data/vhs-sat.db"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL DEFAULT 'folder',
  enabled INTEGER NOT NULL DEFAULT 1,

  folder TEXT,
  rotation TEXT NOT NULL DEFAULT 'random',
  reshuffle_on_loop INTEGER NOT NULL DEFAULT 0,
  file_extensions TEXT NOT NULL DEFAULT 'mp4,mkv,avi,ts,mov,m4v,webm',
  codec_strategy TEXT NOT NULL DEFAULT 'auto',
  bumper_enabled INTEGER NOT NULL DEFAULT 1,
  bumper_duration_sec INTEGER NOT NULL DEFAULT 5,

  hls_enabled INTEGER NOT NULL DEFAULT 1,
  multicast_enabled INTEGER NOT NULL DEFAULT 0,
  multicast_addr TEXT DEFAULT '239.1.1.1',
  multicast_port INTEGER DEFAULT 5000,

  adapter_id TEXT,
  transponder_id INTEGER,
  service_id INTEGER,

  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS channel_state (
  channel_id INTEGER PRIMARY KEY,
  running INTEGER NOT NULL DEFAULT 0,
  started_at TEXT,
  last_error TEXT,
  FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- channels CRUD ----------
def list_channels() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM channels ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_channel(channel_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM channels WHERE id = ?",
                           (channel_id,)).fetchone()
        return dict(row) if row else None


def create_channel(data: dict) -> int:
    fields = [
        "name", "source_type", "folder", "rotation", "reshuffle_on_loop",
        "file_extensions", "codec_strategy", "bumper_enabled", "bumper_duration_sec",
        "hls_enabled", "multicast_enabled", "multicast_addr", "multicast_port",
        "enabled",
    ]
    values = [data.get(f) for f in fields]
    cols = ", ".join(fields)
    ph = ", ".join("?" * len(fields))
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO channels ({cols}) VALUES ({ph})", values)
        return cur.lastrowid


def update_channel(channel_id: int, data: dict) -> None:
    allowed = {
        "name", "folder", "rotation", "reshuffle_on_loop", "file_extensions",
        "codec_strategy", "bumper_enabled", "bumper_duration_sec",
        "hls_enabled", "multicast_enabled", "multicast_addr", "multicast_port",
        "enabled",
    }
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return
    sets = ", ".join(f"{k} = ?" for k in updates)
    with get_db() as conn:
        conn.execute(
            f"UPDATE channels SET {sets}, updated_at = datetime('now') WHERE id = ?",
            list(updates.values()) + [channel_id],
        )


def delete_channel(channel_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))


def find_channels_by_folder(folder: str, exclude_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM channels WHERE source_type = 'folder' AND folder = ?",
            (folder,),
        ).fetchall()
    return [dict(r) for r in rows if r["id"] != exclude_id]