"""Launch Packet Tracer itself and check what it actually opened."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import time
from pathlib import Path

PT_EXE = Path(r"D:\Cisco Packet Tracer 8.1.1\bin\PacketTracer.exe")

#: Windows creation flags that let PT outlive the agent process that started it.
#: DSH (and most agent runners) put tool commands in a job object; a plain child
#: would be killed the moment the tool call returns.  CREATE_BREAKAWAY_FROM_JOB
#: escapes that job, DETACHED_PROCESS drops the console handle.
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

_user32 = ctypes.windll.user32
_EnumWindows = _user32.EnumWindows
_EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def find_windows(pid: int) -> list[tuple[int, str]]:
    """Return (hwnd, title) for every visible top level window of *pid*."""
    found: list[tuple[int, str]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        owner = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            found.append((hwnd, buf.value))
        return True

    _EnumWindows(_EnumWindowsProc(callback), 0)
    return found


def open_in_pt(path: str | Path, *, exe: str | Path = PT_EXE) -> int:
    """Start Packet Tracer with *path* and return the process id.

    The process is detached from the caller's job object so it keeps running
    after the agent tool call that opened it has finished.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(
            [str(exe), str(path)],
            cwd=str(Path(exe).parent),
            creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
        )
    except OSError:
        # The surrounding job may forbid breakaway; detached is still better
        # than inheriting the console, so retry without the breakaway bit.
        proc = subprocess.Popen(
            [str(exe), str(path)],
            cwd=str(Path(exe).parent),
            creationflags=flags,
        )
    return proc.pid


def wait_until_open(
    pid: int,
    path: str | Path,
    *,
    timeout: float = 25.0,
    poll: float = 0.5,
) -> tuple[bool, str]:
    """Poll the PT window title until it names *path*.

    Returns (ok, title).  PT shows the file name in its title bar only after a
    successful load; a rejected file keeps a bare "Cisco Packet Tracer" title
    and pops an "Invalid File" dialog.
    """
    name = Path(path).name
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        for _hwnd, title in find_windows(pid):
            last = title or last
            if name in title:
                return True, title
            if "Invalid File" in title:
                return False, title
        time.sleep(poll)
    return False, last


def maximize(pid: int) -> bool:
    """Bring the main PT window of *pid* to the foreground and maximise it."""
    best = None
    for hwnd, title in find_windows(pid):
        if "Cisco Packet Tracer" in title:
            best = hwnd
    if best is None:
        return False
    _user32.ShowWindow(best, 3)  # SW_MAXIMIZE
    _user32.SetForegroundWindow(best)
    return True
