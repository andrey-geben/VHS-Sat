"""Windows stub backend.

Returns demo data so UI and REST can be developed and tested on Windows.
It does NOT talk to any DVB hardware — tune always returns lock=False,
multicast methods return an error explaining that dvblast is Linux-only.
"""
from __future__ import annotations

from .base import DVBBackend


DEMO_ADAPTERS = [
    {
        "id": "a0",
        "device": "STUB:/dev/dvb/adapter0",
        "frontend": 0,
        "name": "Demo TBS 6903 (stub)",
        "capabilities": ["DVB-S", "DVB-S2"],
        "status": "idle",
        "lock": False,
        "signal": {"strength": 0, "snr": 0, "ber": 0},
        "lnb": {"type": "universal", "low": 9750, "high": 10600,
                "voltage": "18V", "tone": "auto"},
        "diseqc": {"version": "1.0", "port": 1},
    },
    {
        "id": "a1",
        "device": "STUB:/dev/dvb/adapter1",
        "frontend": 0,
        "name": "Demo Digital Devices Cine S2 (stub)",
        "capabilities": ["DVB-S", "DVB-S2"],
        "status": "idle",
        "lock": False,
        "signal": {"strength": 0, "snr": 0, "ber": 0},
        "lnb": {"type": "universal", "low": 9750, "high": 10600,
                "voltage": "18V", "tone": "auto"},
        "diseqc": {"version": "1.0", "port": 2},
    },
]

DEMO_CI_SLOTS = [
    {"id": "ci0", "device": "STUB:/dev/dvb/adapter0/ca0", "adapter": "a0",
     "present": True, "cam_type": "STUB CAM (demo)", "status": "ready"},
    {"id": "ci1", "device": "STUB:/dev/dvb/adapter1/ca0", "adapter": "a1",
     "present": False, "cam_type": None, "status": "absent"},
]


class WindowsStubBackend(DVBBackend):
    name = "windows-stub"

    def discover_adapters(self) -> list[dict]:
        return [dict(a) for a in DEMO_ADAPTERS]

    def get_adapter_status(self, adapter_id: str) -> dict:
        for adapter in DEMO_ADAPTERS:
            if adapter["id"] == adapter_id:
                return dict(adapter)
        raise KeyError(adapter_id)

    def set_lnb(self, adapter_id: str, params: dict) -> dict:
        adapter = self.get_adapter_status(adapter_id)
        adapter["lnb"] = {**adapter["lnb"], **params}
        return {"ok": True, "backend": self.name, "adapter": adapter}

    def apply_diseqc(self, adapter_id: str, params: dict) -> dict:
        return {"ok": True, "backend": self.name, "applied": False,
                "note": "stub: DiSEqC saved to config, no hardware"}

    def tune(self, adapter_id: str, params: dict) -> dict:
        return {"ok": True, "backend": self.name, "lock": False,
                "reason": "stub backend does not talk to hardware"}

    def scan(self, adapter_id: str, params: dict) -> list[dict]:
        return []

    def list_ci_slots(self) -> list[dict]:
        return [dict(c) for c in DEMO_CI_SLOTS]

    def get_ci_status(self, ci_id: str) -> dict:
        for slot in DEMO_CI_SLOTS:
            if slot["id"] == ci_id:
                return dict(slot)
        raise KeyError(ci_id)

    def start_multicast(self, service_id: str, addr: str, port: int) -> dict:
        return {"ok": False, "backend": self.name,
                "reason": "multicast requires Linux + dvblast"}

    def stop_multicast(self, service_id: str) -> dict:
        return {"ok": False, "backend": self.name}

    def list_multicasts(self) -> list[dict]:
        return []