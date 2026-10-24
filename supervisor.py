"""Per-channel ffmpeg supervisor. One thread per channel,
one subprocess per enabled output."""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from event_writer import events
from sources import FolderSource


class ChannelRunner(threading.Thread):
    def __init__(self, channel: dict):
        super().__init__(daemon=True, name=f"channel-{channel['id']}")
        self.channel = channel
        self.stop_event = threading.Event()
        self.procs: dict[str, subprocess.Popen] = {}
        self.state: dict = {
            "running": False,
            "started_at": None,
            "current_file": None,
            "position_sec": 0,
            "error": None,
        }

    # ---------- public ----------
    def stop(self) -> None:
        self.stop_event.set()

    def enabled_outputs(self) -> list[str]:
        outs = []
        if self.channel.get("hls_enabled"):
            outs.append("hls")
        if self.channel.get("multicast_enabled"):
            outs.append("multicast")
        return outs

    # ---------- thread body ----------
    def run(self) -> None:
        self.state["running"] = True
        self.state["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            source = FolderSource(self.channel)
            outputs = self.enabled_outputs()
            if not outputs:
                raise RuntimeError("no output enabled (hls/multicast)")

            for out in outputs:
                cmd = source.build_ffmpeg_cmd(out)
                events.info("supervisor",
                            f"channel {self.channel['id']} start output={out}",
                            cmd=" ".join(cmd[:8]) + " ...")
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1,
                )
                self.procs[out] = proc
                threading.Thread(
                    target=self._read_progress, args=(out, proc), daemon=True,
                ).start()
                threading.Thread(
                    target=self._read_stderr, args=(out, proc), daemon=True,
                ).start()

            # monitor
            while not self.stop_event.is_set():
                time.sleep(1.0)
                alive = [p for p in self.procs.values() if p.poll() is None]
                if not alive:
                    break

        except Exception as exc:  # noqa: BLE001
            self.state["error"] = str(exc)
            events.error("supervisor",
                         f"channel {self.channel['id']} crashed: {exc}")
        finally:
            self._cleanup()
            self.state["running"] = False
            events.info("supervisor",
                        f"channel {self.channel['id']} stopped")

    # ---------- helpers ----------
    def _read_progress(self, out: str, proc: subprocess.Popen) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    ms = int(line.split("=", 1)[1])
                    self.state["position_sec"] = ms // 1_000_000
                except ValueError:
                    pass

    def _read_stderr(self, out: str, proc: subprocess.Popen) -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            line = line.rstrip()
            if not line:
                continue
            low = line.lower()
            if "opening" in low and "for reading" in low:
                # best-effort now-playing from ffmpeg log
                name = line.split("'", 2)[-2] if "'" in line else line
                self.state["current_file"] = Path(name).name
            if any(w in low for w in ("error", "failed", "invalid")):
                events.warn("ffmpeg", f"channel {self.channel['id']} [{out}]: {line[-300:]}")

    def _cleanup(self) -> None:
        for name, p in list(self.procs.items()):
            if p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        self.procs.clear()


class Supervisor:
    def __init__(self) -> None:
        self.runners: dict[int, ChannelRunner] = {}
        self._lock = threading.Lock()

    def start(self, channel: dict) -> bool:
        cid = channel["id"]
        with self._lock:
            existing = self.runners.get(cid)
            if existing and existing.is_alive():
                return False
            runner = ChannelRunner(channel)
            self.runners[cid] = runner
            runner.start()
            return True

    def stop(self, channel_id: int) -> bool:
        with self._lock:
            runner = self.runners.pop(channel_id, None)
        if not runner:
            return False
        runner.stop()
        runner.join(timeout=15)
        return True

    def get_state(self, channel_id: int) -> dict:
        runner = self.runners.get(channel_id)
        if runner:
            return dict(runner.state)
        return {"running": False}

    def list_states(self) -> dict[int, dict]:
        return {cid: dict(r.state) for cid, r in self.runners.items()}

    def shutdown_all(self) -> None:
        for cid in list(self.runners.keys()):
            self.stop(cid)


supervisor = Supervisor()