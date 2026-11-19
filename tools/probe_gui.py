"""Probe: can we open a device window in Packet Tracer with synthetic input?"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ptforge import gui

TARGET = "office_lan_v6.pkt"
CANVAS_OFFSET = (1, 144)  # screen = canvas + offset (measured at 1920x1080 maximized)


def main() -> int:
    matches = gui.list_windows(TARGET)
    if not matches:
        print("PT window not found; start it first")
        return 1
    hwnd, title = matches[0]
    print("window:", hwnd, title)
    print("activated:", gui.activate(hwnd))
    time.sleep(1.0)
    print("foreground:", gui.foreground())

    out = Path("fixtures/probe")
    out.mkdir(exist_ok=True)
    gui.screenshot(out / "00_before.png")

    # PC0 sits at canvas (225, 540) in office_lan_v6.pkt
    x, y = 225 + CANVAS_OFFSET[0], 540 + CANVAS_OFFSET[1]
    gui.click(x, y)
    time.sleep(0.5)
    gui.screenshot(out / "01_selected.png")

    gui.double_click(x, y)
    time.sleep(2.0)
    gui.screenshot(out / "02_double.png")
    print("foreground after double-click:", gui.foreground())

    # Any new top-level windows owned by the same process?
    fg_hwnd, _fg_title = gui.foreground()
    pid = gui.wt.DWORD()
    gui.user32.GetWindowThreadProcessId(fg_hwnd, gui.ctypes.byref(pid))
    print("windows of pid", pid.value)
    for h, name in gui.windows_of_pid(pid.value):
        print("   ", h, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
