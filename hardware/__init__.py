"""Hardware backend factory.

Picks LinuxDVBBackend on Linux, WindowsStubBackend everywhere else.
The rest of the code only talks to the abstract DVBBackend interface.
"""
from __future__ import annotations

import platform

from .base import DVBBackend


def create_backend() -> DVBBackend:
    if platform.system() == "Linux":
        from .linux_backend import LinuxDVBBackend
        return LinuxDVBBackend()
    from .windows_stub import WindowsStubBackend
    return WindowsStubBackend()


backend = create_backend()