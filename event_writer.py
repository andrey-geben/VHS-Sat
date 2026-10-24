"""JSONL event writer, modelled after VHS-Streamer's EventWriter."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import config


class EventWriter:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            path = config.get("logging", "events_file", default="logs/events.jsonl")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.Lock()

    def write(self, level: str, source: str, message: str, **extra: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": level.upper(),
            "source": source,
            "message": message,
        }
        if extra:
            record["extra"] = extra
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def info(self, source: str, message: str, **kw: Any) -> None:
        self.write("INFO", source, message, **kw)

    def warn(self, source: str, message: str, **kw: Any) -> None:
        self.write("WARN", source, message, **kw)

    def error(self, source: str, message: str, **kw: Any) -> None:
        self.write("ERROR", source, message, **kw)

    def read_tail(self, limit: int = 200) -> list[dict]:
        if not self.path.exists():
            return []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()[-limit:]
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result


events = EventWriter()