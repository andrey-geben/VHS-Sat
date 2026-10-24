"""Abstract DVB hardware backend interface.

All platform-specific code lives in subclasses. UI / REST / config layers
only see this interface — that's what makes VHS-Sat cross-platform
for development while keeping real DVB work Linux-only.
"""
from __future__ import annotations


class DVBBackend:
    """Contract: adapters, LNB/DiSEqC, tune, scan, CI, multicast."""

    name: str = "abstract"

    # --- discovery ---
    def discover_adapters(self) -> list[dict]:
        raise NotImplementedError

    def get_adapter_status(self, adapter_id: str) -> dict:
        raise NotImplementedError

    # --- LNB / DiSEqC / tuning ---
    def set_lnb(self, adapter_id: str, params: dict) -> dict:
        raise NotImplementedError

    def apply_diseqc(self, adapter_id: str, params: dict) -> dict:
        """Send DiSEqC 1.0/1.1 command. Applied only when tuning in stage 2."""
        raise NotImplementedError

    def tune(self, adapter_id: str, params: dict) -> dict:
        raise NotImplementedError

    def scan(self, adapter_id: str, params: dict) -> list[dict]:
        raise NotImplementedError

    # --- CI / CAM ---
    def list_ci_slots(self) -> list[dict]:
        raise NotImplementedError

    def get_ci_status(self, ci_id: str) -> dict:
        raise NotImplementedError

    # --- multicast relay ---
    def start_multicast(self, service_id: str, addr: str, port: int) -> dict:
        raise NotImplementedError

    def stop_multicast(self, service_id: str) -> dict:
        raise NotImplementedError

    def list_multicasts(self) -> list[dict]:
        raise NotImplementedError