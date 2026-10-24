"""Linux backend — real DVB hardware.

Stage 0: discovery only (Stage 0 kept the filesystem check).
Stage 1 (this file):
  - discover_adapters(): add capabilities via dvb-fe-tool -g when available
  - set_lnb(): apply voltage / 22 kHz via dvb-fe-tool
  - apply_diseqc(): saved to config only, applied during tune (stage 2)
Tune / scan / multicast / CI streaming: stage 2+.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

from event_writer import events
from .base import DVBBackend


DVB_ROOT = "/dev/dvb"

# Maps our config values to dvb-fe-tool CLI values.
_VOLTAGE_TO_CLI = {"off": "OFF", "13v": "13V", "18v": "18V"}
_TONE_TO_CLI = {"on": "1", "off": "0"}  # "auto" is not applied — decided at tune time

_CAPABILITY_TOKENS = (
    "DVB-S2X", "DVB-S2", "DVB-S", "DVB-C", "DVB-T2", "DVB-T", "ISDB-S",
)


class LinuxDVBBackend(DVBBackend):
    name = "linux-dvb"

    # ---------- helpers ----------
    def _adapter_dirs(self) -> list[str]:
        return sorted(glob.glob(f"{DVB_ROOT}/adapter*"))

    def _frontends(self, adapter_dir: str) -> list[str]:
        return sorted(glob.glob(f"{adapter_dir}/frontend*"))

    def _ca_slots(self, adapter_dir: str) -> list[str]:
        return sorted(glob.glob(f"{adapter_dir}/ca*"))

    def _run(self, cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            events.warn("dvb", f"timeout: {' '.join(cmd)}", timeout=timeout)
            raise RuntimeError(f"timeout: {' '.join(cmd)}") from exc
        except FileNotFoundError as exc:
            events.error("dvb", f"not installed: {cmd[0]}")
            raise RuntimeError(f"not installed: {cmd[0]}") from exc

    def _frontend_info(self, ad_idx: str, fe_idx: str) -> dict:
        """Best-effort parse of `dvb-fe-tool -a N -f M -g`."""
        info = {"capabilities": [], "name": None}
        if not shutil.which("dvb-fe-tool"):
            return info
        try:
            r = self._run(["dvb-fe-tool", "-a", ad_idx, "-f", fe_idx, "-g"], timeout=3.0)
        except RuntimeError:
            return info
        if r.returncode != 0:
            return info
        out = r.stdout or ""

        m = re.search(r"Device\s+(.+?)\s+\(", out)
        if m:
            info["name"] = m.group(1).strip()

        for token in _CAPABILITY_TOKENS:
            if token in out and token not in info["capabilities"]:
                info["capabilities"].append(token)
        return info

    # ---------- discovery ----------
    def discover_adapters(self) -> list[dict]:
        adapters = []
        for adapter_dir in self._adapter_dirs():
            adapter_name = os.path.basename(adapter_dir)          # adapter0
            ad_idx = adapter_name.replace("adapter", "")
            for fe_path in self._frontends(adapter_dir):
                fe_idx = os.path.basename(fe_path).replace("frontend", "")
                adapter_id = (
                    f"a{ad_idx}" if fe_idx == "0" else f"a{ad_idx}f{fe_idx}"
                )
                fe_info = self._frontend_info(ad_idx, fe_idx)
                adapters.append({
                    "id": adapter_id,
                    "device": adapter_dir,
                    "frontend": int(fe_idx),
                    "name": fe_info["name"] or f"{adapter_name}/frontend{fe_idx}",
                    "capabilities": fe_info["capabilities"],
                    "status": "idle",
                    "lock": False,
                    "signal": {"strength": 0, "snr": 0, "ber": 0},
                    "lnb": {"type": "universal", "low": 9750, "high": 10600,
                            "voltage": "off", "tone": "auto"},
                    "diseqc": {"version": "1.0", "port": 1},
                })
        return adapters

    def get_adapter_status(self, adapter_id: str) -> dict:
        for adapter in self.discover_adapters():
            if adapter["id"] == adapter_id:
                return adapter
        raise KeyError(adapter_id)

    # ---------- LNB / DiSEqC ----------
    def set_lnb(self, adapter_id: str, params: dict) -> dict:
        """Apply voltage and 22 kHz tone via dvb-fe-tool.

        params: {type?, low?, high?, voltage: off|13V|18V, tone: auto|on|off}
        Returns {"ok": bool, "details": {...}, "reason"?: str}
        """
        try:
            adapter = self.get_adapter_status(adapter_id)
        except KeyError:
            return {"ok": False, "reason": "adapter not found"}

        if not shutil.which("dvb-fe-tool"):
            return {"ok": False,
                    "reason": "dvb-fe-tool not found (apt install dvb-tools)"}

        ad_idx = adapter["device"].replace(f"{DVB_ROOT}/adapter", "")
        fe_idx = str(adapter["frontend"])
        details: dict[str, dict] = {}

        voltage = (params.get("voltage") or "").lower()
        if voltage in _VOLTAGE_TO_CLI:
            cli = _VOLTAGE_TO_CLI[voltage]
            try:
                r = self._run(["dvb-fe-tool", "-a", ad_idx, "-f", fe_idx,
                               "-v", cli])
                details["voltage"] = {"value": cli, "rc": r.returncode,
                                      "stderr": (r.stderr or "").strip()}
            except RuntimeError as exc:
                details["voltage"] = {"value": cli, "rc": -1, "stderr": str(exc)}

        tone = (params.get("tone") or "").lower()
        if tone in _TONE_TO_CLI:  # "auto" intentionally skipped
            cli = _TONE_TO_CLI[tone]
            try:
                r = self._run(["dvb-fe-tool", "-a", ad_idx, "-f", fe_idx,
                               "-t", cli])
                details["tone"] = {"value": cli, "rc": r.returncode,
                                   "stderr": (r.stderr or "").strip()}
            except RuntimeError as exc:
                details["tone"] = {"value": cli, "rc": -1, "stderr": str(exc)}

        if not details:
            return {"ok": True, "details": {},
                    "note": "nothing to apply (voltage=off+auto? or missing)"}

        all_ok = all(d.get("rc") == 0 for d in details.values())
        return {"ok": all_ok, "details": details}

    def apply_diseqc(self, adapter_id: str, params: dict) -> dict:
        # DiSEqC ioctl cannot be sent without an active tuning session.
        # Config is already saved; actual send happens at tune (stage 2).
        return {"ok": False, "applied": False,
                "reason": "DiSEqC is sent during tune (stage 2); config saved only"}

    # ---------- CI ----------
    def list_ci_slots(self) -> list[dict]:
        slots = []
        for adapter_dir in self._adapter_dirs():
            adapter_name = os.path.basename(adapter_dir)
            ad_idx = adapter_name.replace("adapter", "")
            adapter_id = f"a{ad_idx}"
            for ca_path in self._ca_slots(adapter_dir):
                ca_idx = os.path.basename(ca_path).replace("ca", "")
                slots.append({
                    "id": f"ci{ad_idx}_{ca_idx}",
                    "device": ca_path,
                    "adapter": adapter_id,
                    "present": True,
                    "cam_type": None,
                    "status": "present",
                })
        return slots

    def get_ci_status(self, ci_id: str) -> dict:
        for slot in self.list_ci_slots():
            if slot["id"] == ci_id:
                return slot
        raise KeyError(ci_id)

    # ---------- later stages ----------
    def tune(self, adapter_id, params):
        raise NotImplementedError("stage 2: tune via dvbv5-zap")

    def scan(self, adapter_id, params):
        raise NotImplementedError("stage 2: scan via dvbv5-scan")

    def start_multicast(self, service_id, addr, port):
        raise NotImplementedError("stage 3: multicast via dvblast")

    def stop_multicast(self, service_id):
        raise NotImplementedError("stage 3: stop via dvblast")

    def list_multicasts(self):
        raise NotImplementedError("stage 3: multicast via dvblast")