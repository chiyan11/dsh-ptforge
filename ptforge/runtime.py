"""Run commands inside a Packet Tracer device console.

Packet Tracer keeps every device's CLI in a Qt widget that ignores synthetic
key events, but it does honour clipboard paste (Ctrl+V). So the runtime path is:
bring the device window forward, click into its console, paste each command,
press Enter, and grab a screenshot as evidence.

Reading the console text back is intentionally left to the caller: the widget
has no selectable text and no copy-out API, so the screenshot is the honest
record. The agent (or a human) reads it; `pt_check` covers everything that can
be proven offline.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import gui

__all__ = ["ConsoleError", "exec_commands", "find_device_window"]


class ConsoleError(RuntimeError):
    pass


def find_device_window(device: str, *, timeout: float = 5.0) -> tuple[int, str]:
    """Locate the top-level window PT opened for ``device`` (title == name)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, title in gui.list_windows(device):
            if title.strip().casefold() == device.strip().casefold():
                return hwnd, title
        time.sleep(0.2)
    raise ConsoleError(
        f"no Packet Tracer window titled {device!r}; open the device first "
        "(double-click it on the canvas) or pass --open"
    )


def exec_commands(
    device: str,
    commands: list[str],
    *,
    out: str | Path | None = None,
    wait: float = 1.2,
    fx: float = 0.5,
    fy: float = 0.62,
    read: bool = True,
) -> dict:
    """Paste ``commands`` into the device console and screenshot the result."""
    if not commands:
        raise ConsoleError("no commands to run")
    hwnd, title = find_device_window(device)
    gui.activate(hwnd, maximize=False)
    time.sleep(0.5)
    point = gui.console_click(hwnd, fx=fx, fy=fy)
    time.sleep(0.3)

    results: list[dict] = []
    for command in commands:
        if not gui.set_clipboard(command):
            raise ConsoleError("could not put the command on the clipboard")
        # Ctrl+V is not bound in PT's console; its context menu Paste is.
        gui.context_paste(point[0], point[1])
        gui.press("enter")
        time.sleep(wait)
        results.append({"command": command, "pasted": True})

    left, top, right, bottom = gui.window_rect(hwnd)
    target = Path(out) if out else Path("fixtures") / f"console_{device}.png"
    gui.screenshot(target, region=(left, top, right - left, bottom - top))
    transcript = ""
    if read:
        try:
            transcript = gui.console_copy(hwnd)
        except OSError:
            transcript = ""
    return {
        "device": device,
        "window": title,
        "click": list(point),
        "commands": results,
        "output": transcript,
        "screenshot": str(target),
        "bytes": target.stat().st_size if target.exists() else 0,
    }


def check_output(device: str, checks: list[dict], *, wait: float = 2.0) -> dict:
    """Run commands and assert on their transcript.

    Each check is ``{command, contains?|regex?|not_contains?}``. Assertions run
    against the whole console transcript, which is what PT actually printed.
    """
    if not checks:
        raise ConsoleError("no checks to run")
    commands = []
    for check in checks:
        command = check.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ConsoleError("every check needs a non-empty `command`")
        if command not in commands:
            commands.append(command)
    run = exec_commands(device, commands, wait=wait, read=True)
    transcript = run.get("output") or ""
    results: list[dict] = []
    for check in checks:
        command = check["command"]
        problems: list[str] = []
        if "contains" in check and str(check["contains"]) not in transcript:
            problems.append(f"missing {check['contains']!r}")
        if "not_contains" in check and str(check["not_contains"]) in transcript:
            problems.append(f"unexpected {check['not_contains']!r}")
        if "regex" in check:
            try:
                if re.search(str(check["regex"]), transcript, re.MULTILINE) is None:
                    problems.append(f"regex {check['regex']!r} did not match")
            except re.error as error:
                problems.append(f"bad regex: {error}")
        results.append(
            {
                "command": command,
                "expect": {key: value for key, value in check.items() if key != "command"},
                "ok": not problems,
                "problems": problems,
            }
        )
    return {
        "device": device,
        "ok": all(item["ok"] for item in results),
        "results": results,
        "output": transcript,
        "screenshot": run.get("screenshot"),
    }

_PING_SUMMARY = re.compile(
    r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)\s*\((\d+)%\s*loss\)",
    re.IGNORECASE,
)


def ping(device: str, target: str, *, count: int = 4, wait: float = 8.0) -> dict:
    """Ping ``target`` from ``device`` and parse the summary PT prints."""
    command = f"ping {target}" if count == 4 else f"ping {target} -n {count}"
    run = exec_commands(device, [command], wait=wait, read=True)
    transcript = run.get("output") or ""
    match = _PING_SUMMARY.search(transcript)
    if not match:
        raise ConsoleError(f"no ping summary in the console output for {target!r}")
    sent, received, lost, loss = (int(value) for value in match.groups())
    return {
        "device": device,
        "target": target,
        "sent": sent,
        "received": received,
        "lost": lost,
        "loss_percent": loss,
        "ok": received > 0,
        "output": transcript,
        "screenshot": run.get("screenshot"),
    }


_HTTP_FAILURES = (
    "Request Timeout",
    "Host Unreachable",
    "Host unreachable",
    "Not Supported",
    "Timed Out",
    "Destination",
    "Error 404",
    "Failed to",
)


def http_get(
    device: str,
    url: str,
    *,
    wait: float = 3.0,
    out: str | Path | None = None,
) -> dict:
    """Load ``url`` in the device's Web Browser app and return the page text.

    The browser must already be open on the device's Desktop tab. The URL field
    is a plain Qt line edit (Ctrl+V works), the page body is a text widget whose
    selection copies with Ctrl+C.
    """
    hwnd, title = find_device_window(device)
    gui.activate(hwnd, maximize=False)
    time.sleep(0.5)
    left, top, right, bottom = gui.window_rect(hwnd)
    width, height = right - left, bottom - top

    url_point = (int(left + width * 0.45), int(top + height * 0.161))
    go_point = (int(left + width * 0.80), int(top + height * 0.161))
    gui.click(*url_point)
    time.sleep(0.25)
    gui.hotkey("ctrl", "a")  # replace whatever is already in the field
    time.sleep(0.1)
    gui.set_clipboard(url)
    gui.hotkey("ctrl", "v")
    time.sleep(0.25)
    gui.click(*go_point)
    time.sleep(wait)

    # Clear the URL field selection first, otherwise Ctrl+C re-copies the URL.
    gui.click(int(left + width * 0.5), int(top + height * 0.5))
    time.sleep(0.2)
    gui.set_clipboard("")
    gui.drag(int(left + width * 0.056), int(top + height * 0.21),
             int(left + width * 0.944), int(top + height * 0.60))
    time.sleep(0.25)
    gui.hotkey("ctrl", "c")
    time.sleep(0.35)
    body = gui.get_clipboard()

    target = Path(out) if out else Path("fixtures") / f"http_{device}.png"
    gui.screenshot(target, region=(left, top, width, height))
    failed = any(marker in body for marker in _HTTP_FAILURES)
    return {
        "device": device,
        "window": title,
        "url": url,
        "body": body,
        "ok": bool(body.strip()) and not failed,
        "screenshot": str(target),
    }






def _console_text(hwnd: int) -> str:
    """Read the console transcript (selection + context-menu Copy)."""
    try:
        return gui.console_copy(hwnd) or ""
    except OSError:
        return ""


def _send_line(hwnd: int, point: tuple[int, int], text: str, *, settle: float = 0.35) -> None:
    if not gui.set_clipboard(text):
        raise ConsoleError("could not put the command on the clipboard")
    gui.context_paste(point[0], point[1])
    gui.press("enter")
    time.sleep(settle)


def ftp_session(
    device: str,
    server: str,
    *,
    username: str = "cisco",
    password: str = "cisco",
    commands: list[str] | None = None,
    wait: float = 3.0,
    out: str | Path | None = None,
) -> dict:
    """Run an FTP session from a PC console and return the transcript.

    PT's console is prompt-driven, so every step waits for its prompt
    (``Username:``, ``Password:``, ``ftp>``) instead of relying on fixed delays.
    """
    commands = commands or ["dir"]
    hwnd, title = find_device_window(device)
    gui.activate(hwnd, maximize=False)
    time.sleep(0.5)
    left, top, right, bottom = gui.window_rect(hwnd)
    point = (int(left + (right - left) * 0.5), int(top + (bottom - top) * 0.62))
    gui.click(*point)
    time.sleep(0.3)

    transcript = ""
    best = ""
    steps: list[dict] = []

    def step(label: str, text: str, token: str, *, timeout: float) -> None:
        nonlocal transcript, best
        _send_line(hwnd, point, text)
        deadline = time.time() + timeout
        seen = False
        while time.time() < deadline:
            time.sleep(0.6)
            transcript = _console_text(hwnd)
            if token in transcript[-800:]:
                seen = True
                break
        if len(transcript) > len(best):
            best = transcript
        steps.append({"step": label, "sent": text, "prompt": token, "ok": seen})

    step("connect", f"ftp {server}", "Username:", timeout=wait + 4)
    step("username", username, "Password:", timeout=wait)
    step("password", password, "ftp>", timeout=wait)
    for index, command in enumerate(commands, start=1):
        step(f"command{index}", command, "ftp>", timeout=wait)
    step("quit", "quit", "C:\\>", timeout=wait)

    transcript = _console_text(hwnd)
    if len(transcript) < len(best):
        transcript = best
    target = Path(out) if out else Path("fixtures") / f"ftp_{device}.png"
    gui.screenshot(target, region=(left, top, right - left, bottom - top))
    return {
        "device": device,
        "window": title,
        "server": server,
        "steps": steps,
        "output": transcript,
        "screenshot": str(target),
        "ok": all(item["ok"] for item in steps),
    }



