"""Environment and file compatibility checks.

A generated topology that Packet Tracer silently refuses is worse than a
clear error, so every build path can ask this module first whether the host
can actually run what we are about to write.
"""

from __future__ import annotations

from pathlib import Path

from .ptcrypto import ptfile

__all__ = ["DoctorError", "SUPPORTED_PREFIX", "environment", "verify_file"]

SUPPORTED_PREFIX = "8.1."
PT_EXE = Path(r"D:\Cisco Packet Tracer 8.1.1\bin\PacketTracer.exe")


class DoctorError(RuntimeError):
    """Raised when the host cannot run the requested topology."""


def environment() -> dict:
    issues: list[str] = []
    exe = PT_EXE if PT_EXE.is_file() else None
    if exe is None:
        issues.append(
            f"Packet Tracer executable not found at {PT_EXE}; install Packet Tracer "
            "8.1.1 or set PT_EXE before opening files"
        )
    pillow = True
    try:
        import PIL  # noqa: F401
    except ImportError:  # pragma: no cover - optional dependency
        pillow = False
        issues.append("Pillow is not installed; screenshots are unavailable")
    return {
        "ok": not issues,
        "packet_tracer": str(exe) if exe else None,
        "pillow": pillow,
        "supported_prefix": SUPPORTED_PREFIX,
        "issues": issues,
    }


def verify_file(path: str | Path) -> dict:
    """Decode a ``.pkt`` and report whether Packet Tracer 8.1 can load it."""
    path = Path(path)
    issues: list[str] = []
    if not path.is_file():
        raise DoctorError(f"{path} does not exist")
    try:
        root = ptfile.decode(str(path))
    except Exception as exc:  # noqa: BLE001 - surface the real decoder message
        raise DoctorError(f"{path.name} is not a readable .pkt: {exc}") from exc
    version = root.findtext("VERSION") or ""
    if not version.startswith(SUPPORTED_PREFIX):
        issues.append(
            f"file version {version or '?'} is not {SUPPORTED_PREFIX}x; "
            "Packet Tracer 8.1.1 expects a 8.1 container"
        )
    devices = len(root.findall("NETWORK/DEVICES/DEVICE"))
    links = len(root.findall("NETWORK/LINKS/LINK"))
    if devices == 0:
        issues.append("topology has no devices")
    return {
        "ok": not issues,
        "path": str(path),
        "version": version,
        "devices": devices,
        "links": links,
        "bytes": path.stat().st_size,
        "issues": issues,
    }
