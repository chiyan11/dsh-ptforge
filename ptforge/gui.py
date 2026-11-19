"""Windows GUI helpers for driving Packet Tracer from Python.

Packet Tracer has no automation API, so the runtime half of the engine drives
its Qt windows with synthetic input and reads pixels back. Everything here is
dependency free (ctypes + Pillow) and works without elevation.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_MAXIMIZE = 3
SW_RESTORE = 9
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def list_windows(needle: str = "") -> list[tuple[int, str]]:
    """Visible top-level windows whose title contains ``needle``."""
    found: list[tuple[int, str]] = []

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if needle.lower() in buf.value.lower():
                    found.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found


def windows_of_pid(pid: int) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def _cb(hwnd, _lparam):
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            found.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return found


def foreground() -> tuple[int, str]:
    hwnd = int(user32.GetForegroundWindow())
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return hwnd, buf.value


def _thread_of(hwnd: int) -> int:
    return int(user32.GetWindowThreadProcessId(hwnd, None))


def activate(hwnd: int, *, maximize: bool = True) -> bool:
    """Bring ``hwnd`` to the foreground, working around the foreground lock.

    Plain ``SetForegroundWindow`` silently fails when the calling process does
    not already own the foreground, which is exactly the case for an agent
    driving Packet Tracer from the background. Attaching to the foreground
    thread's input queue lifts that restriction.
    """
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_MAXIMIZE if maximize else SW_RESTORE)
    for _ in range(4):
        fg = int(user32.GetForegroundWindow())
        if fg == hwnd:
            return True
        current = kernel32.GetCurrentThreadId()
        foreground_thread = _thread_of(fg) if fg else 0
        attached = False
        if foreground_thread:
            attached = bool(user32.AttachThreadInput(current, foreground_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        if attached:
            user32.AttachThreadInput(current, foreground_thread, False)
        time.sleep(0.25)
        if int(user32.GetForegroundWindow()) == hwnd:
            return True
    return False


def _send(*inputs: INPUT) -> None:
    array = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))


def _mouse(flags: int, x: int, y: int) -> INPUT:
    return INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(dx=x, dy=y, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None),
    )


def move(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)


def click(x: int, y: int, *, button: str = "left") -> None:
    down, up = (
        (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
        if button == "left"
        else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    )
    move(x, y)
    _send(_mouse(down, x, y))
    time.sleep(0.04)
    _send(_mouse(up, x, y))
    time.sleep(0.08)


def double_click(x: int, y: int, *, gap: float = 0.12) -> None:
    move(x, y)
    for _ in range(2):
        _send(_mouse(MOUSEEVENTF_LEFTDOWN, x, y))
        time.sleep(0.03)
        _send(_mouse(MOUSEEVENTF_LEFTUP, x, y))
        time.sleep(gap)


def type_text(text: str) -> None:
    """Type a string as unicode, one character at a time."""
    for char in text:
        code = ord(char)
        _send(
            INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)),
            INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(
                    wVk=0,
                    wScan=code,
                    dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        time.sleep(0.012)


VK = {
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "space": 0x20,
    "back": 0x08,
    "up": 0x26,
    "down": 0x28,
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
}


def press(key: str) -> None:
    """Press a named key or a lowercase character."""
    vk = VK.get(key) or ord(key.upper())
    _send(
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)),
        INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None),
        ),
    )
    time.sleep(0.05)


def _vk(key: str) -> int:
    if key in VK:
        return VK[key]
    if len(key) == 1:
        return ord(key.upper())
    raise ValueError(f"unknown key name: {key!r}")


def hotkey(*keys: str) -> None:
    vks = [_vk(k) for k in keys]
    for vk in vks:
        _send(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)))
        time.sleep(0.02)
    for vk in reversed(vks):
        _send(
            INPUT(
                type=INPUT_KEYBOARD,
                ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None),
            )
        )
        time.sleep(0.02)


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wt.HWND]
user32.OpenClipboard.restype = wt.BOOL
user32.EmptyClipboard.restype = wt.BOOL
user32.CloseClipboard.restype = wt.BOOL
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GlobalFree.argtypes = [wt.HGLOBAL]


def _open_clipboard(tries: int = 10) -> bool:
    for _ in range(tries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.1)
    return False


def set_clipboard(text: str) -> bool:
    """Put unicode text on the clipboard (works from any integrity level the
    caller is allowed to write from)."""
    data = str(text).encode("utf-16-le") + b"\x00\x00"
    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


def get_clipboard() -> str:
    """Read unicode text off the clipboard; empty string when unavailable."""
    if not _open_clipboard():
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def paste_text(text: str, *, settle: float = 0.2) -> bool:
    """Deliver text through the clipboard and Ctrl+V (bypasses per-key IME)."""
    if not set_clipboard(text):
        return False
    time.sleep(0.1)
    hotkey("ctrl", "v")
    time.sleep(settle)
    return True


def screenshot(path: str | Path, *, region: tuple[int, int, int, int] | None = None) -> Path:
    """Grab the screen (or a region) to a PNG file."""
    from PIL import ImageGrab

    image = ImageGrab.grab(all_screens=False)
    if region:
        image = image.crop((region[0], region[1], region[0] + region[2], region[1] + region[3]))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


def wait_window(needle: str, timeout: float = 10.0) -> tuple[int, str] | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        matches = list_windows(needle)
        if matches:
            return matches[0]
        time.sleep(0.2)
    return None

def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of a window in screen pixels."""
    rect = wt.RECT()
    if not user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
        raise OSError(f"GetWindowRect failed for {hwnd}")
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def console_click(hwnd: int, *, fx: float = 0.5, fy: float = 0.6) -> tuple[int, int]:
    """Click inside the body of a device window (the console area)."""
    left, top, right, bottom = window_rect(hwnd)
    x = int(left + (right - left) * fx)
    y = int(top + (bottom - top) * fy)
    click(x, y)
    return x, y

def context_paste(x: int, y: int, *, dx: int = 45, dy: int = 34, settle: float = 0.5) -> bool:
    """Paste through a widget's right-click menu.

    Packet Tracer's console does not bind Ctrl+V, but its context menu offers
    Paste. The menu opens with its top-left at the pointer, so the item offset
    is stable for a given DPI.
    """
    move(x, y)
    click(x, y, button="right")
    time.sleep(settle)
    click(x + dx, y + dy)
    time.sleep(settle)
    return True

def drag(x0: int, y0: int, x1: int, y1: int, *, steps: int = 14, duration: float = 0.4) -> None:
    """Press at (x0, y0), glide to (x1, y1), release -- for text selection."""
    move(x0, y0)
    time.sleep(0.06)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN, 0, 0))
    for index in range(1, steps + 1):
        x = int(x0 + (x1 - x0) * index / steps)
        y = int(y0 + (y1 - y0) * index / steps)
        move(x, y)
        time.sleep(duration / steps)
    _send(_mouse(MOUSEEVENTF_LEFTUP, 0, 0))
    time.sleep(0.1)


def console_select(hwnd: int, *, fx0: float = 0.06, fy0: float = 0.24,
                   fx1: float = 0.94, fy1: float = 0.95) -> tuple[int, int]:
    """Select the whole console transcript with a mouse drag."""
    left, top, right, bottom = window_rect(hwnd)
    width, height = right - left, bottom - top
    drag(int(left + width * fx0), int(top + height * fy0),
         int(left + width * fx1), int(top + height * fy1))
    return int(left + width * fx0), int(top + height * fy0)


def console_copy(hwnd: int, *, dx: int = 40, dy: int = 20) -> str:
    """Select the console transcript and copy it through the context menu."""
    left, top, right, bottom = window_rect(hwnd)
    cx = int((left + right) / 2)
    cy = int(top + (bottom - top) * 0.6)
    console_select(hwnd)
    time.sleep(0.25)
    click(cx, cy, button="right")
    time.sleep(0.45)
    click(cx + dx, cy + dy)
    time.sleep(0.45)
    return get_clipboard()

