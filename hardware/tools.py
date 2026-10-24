"""Detection of external binaries used by the Linux backend."""
from __future__ import annotations

import shutil


TOOLS = {
    "dvblast":     "мультикаст MPEG-TS, CAM/CI",
    "dvb-fe-tool": "управление LNB (напряжение, 22kHz), capabilities",
    "dvbv5-zap":   "тюнинг + мониторинг сигнала",
    "dvbv5-scan":  "сканирование транспондера",
    "ffmpeg":      "HLS, локальные каналы, запись",
    "ffprobe":     "длительность и параметры видеофайлов",
}


def detect_tools() -> dict[str, str | None]:
    """Returns {tool_name: absolute_path or None}."""
    return {name: shutil.which(name) for name in TOOLS}