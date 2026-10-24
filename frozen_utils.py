"""Path resolution that works both as script and as frozen .exe."""
import sys
from pathlib import Path


def _app_root() -> Path:
    """Folder next to the .exe (or the project root when run as script)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    """Folder with templates/static. In onefile this is sys._MEIPASS."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


APP_ROOT = _app_root()          # writable: config.yaml, data/, logs/
RESOURCE_ROOT = _resource_dir() # read-only: templates/, static/


def find_tool(name: str) -> str | None:
    """Locate ffmpeg/ffprobe: bundled bin/ first, then PATH."""
    exe = ".exe" if sys.platform == "win32" else ""
    bundled = APP_ROOT / "bin" / f"{name}{exe}"
    if bundled.is_file():
        return str(bundled)
    import shutil
    return shutil.which(name)