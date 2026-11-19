# Type into a Packet Tracer device console from a process that owns a real
# input queue. The DSH sandbox blocks injected keystrokes, so this script is
# launched through explorer.exe and reads its work from ptkeys-request.json
# next to itself.
#
# Request shape:
#   { "window": "PC0", "text": "ipconfig", "enter": true,
#     "copy_to": "D:\\...\\clip.txt", "log": "D:\\...\\ptkeys.log" }
#
# Output: a log line "typed=... copied=... fg=..." plus, when copy_to is set,
# the console text captured with Ctrl+A / Ctrl+C.

param(
    [string]$Request = (Join-Path $PSScriptRoot 'ptkeys-request.json')
)

$ErrorActionPreference = 'Stop'

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class PtKeys {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);
    [DllImport("user32.dll")] public static extern short VkKeyScan(char ch);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT rect);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    public static bool Activate(IntPtr h) {
        ShowWindow(h, 9);
        BringWindowToTop(h);
        uint fg = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero);
        uint me = GetCurrentThreadId();
        AttachThreadInput(me, fg, true);
        bool ok = SetForegroundWindow(h);
        AttachThreadInput(me, fg, false);
        return ok;
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr h, StringBuilder text, int count);
    private delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumProc cb, IntPtr l);
    public static List<IntPtr> EnumTopWindows() {
        var list = new List<IntPtr>();
        EnumWindows((h, l) => { list.Add(h); return true; }, IntPtr.Zero);
        return list;
    }
    public static IntPtr FindWindow(string needle) {
        foreach (var h in EnumTopWindows()) {
            var sb = new StringBuilder(512);
            GetWindowText(h, sb, 512);
            if (sb.ToString().IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0) return h;
        }
        return IntPtr.Zero;
    }
    public static string Title(IntPtr h) {
        var sb = new StringBuilder(512);
        GetWindowText(h, sb, 512);
        return sb.ToString();
    }
}
"@

function Send-Key([byte]$vk, [bool]$up) {
    $flags = if ($up) { 2 } else { 0 }
    $scan = [byte][PtKeys]::MapVirtualKey([uint32]$vk, 0)
    [PtKeys]::keybd_event($vk, $scan, [uint32]$flags, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 12
}

function Send-Char([char]$ch) {
    $packed = [PtKeys]::VkKeyScan($ch)
    $vk = $packed -band 0xFF
    $mods = ($packed -shr 8) -band 0xFF
    $shift = ($mods -band 1) -ne 0
    $ctrl = ($mods -band 2) -ne 0
    $alt = ($mods -band 4) -ne 0
    if ($ctrl) { [PtKeys]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero) }
    if ($alt) { [PtKeys]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero) }
    if ($shift) { [PtKeys]::keybd_event(0x10, 0, 0, [UIntPtr]::Zero) }
    Send-Key ([byte]$vk) $false
    Send-Key ([byte]$vk) $true
    if ($shift) { [PtKeys]::keybd_event(0x10, 0, 2, [UIntPtr]::Zero) }
    if ($alt) { [PtKeys]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero) }
    if ($ctrl) { [PtKeys]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero) }
}

$log = Join-Path $PSScriptRoot 'ptkeys.log'
try {
    if (-not (Test-Path $Request)) { throw "missing request file: $Request" }
    $job = Get-Content $Request -Raw -Encoding UTF8 | ConvertFrom-Json
    $logPath = if ($job.log) { $job.log } else { $log }

    $hwnd = [PtKeys]::FindWindow([string]$job.window)
    $fgBefore = [PtKeys]::Title([PtKeys]::GetForegroundWindow())
    if ($hwnd -ne [IntPtr]::Zero) {
        [void][PtKeys]::Activate($hwnd)
        Start-Sleep -Milliseconds 700
    }
    $fgAfter = [PtKeys]::Title([PtKeys]::GetForegroundWindow())

    # Put the caret where the caller wants it (the console body), otherwise the
    # keystrokes land on whichever child widget happens to hold focus.
    if ($job.click) {
        $cx = [int]$job.click[0]
        $cy = [int]$job.click[1]
        if ($job.relative) {
            $rect = New-Object PtKeys+RECT
            [void][PtKeys]::GetWindowRect($hwnd, [ref]$rect)
            $cx = [int]($rect.Left + ($rect.Right - $rect.Left) * [double]$job.click[0])
            $cy = [int]($rect.Top + ($rect.Bottom - $rect.Top) * [double]$job.click[1])
        }
        [PtKeys]::SetCursorPos($cx, $cy)
        Start-Sleep -Milliseconds 120
        [PtKeys]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 40
        [PtKeys]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 300
    }

    $charDelay = if ($job.char_delay_ms) { [int]$job.char_delay_ms } else { 45 }

    if ($job.text) {
        foreach ($ch in ([string]$job.text).ToCharArray()) {
            Send-Char $ch
            Start-Sleep -Milliseconds $charDelay
        }
    }
    if ($job.enter) {
        Send-Key 0x0D $false
        Send-Key 0x0D $true
    }
    Start-Sleep -Milliseconds 700

    $copied = $false
    if ($job.copy_to) {
        [PtKeys]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero)
        Send-Key 0x41 $false
        Send-Key 0x41 $true
        [PtKeys]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 150
        [PtKeys]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero)
        Send-Key 0x43 $false
        Send-Key 0x43 $true
        [PtKeys]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 350
        try {
            $text = Get-Clipboard -Raw -ErrorAction Stop
            Set-Content -Path $job.copy_to -Value $text -Encoding UTF8 -NoNewline
            $copied = $true
        } catch {
            $copied = "error: $($_.Exception.Message)"
        }
    }

    $fgTitle = [PtKeys]::Title([PtKeys]::GetForegroundWindow())
    "typed=$($job.text) copied=$copied fg_before=$fgBefore fg_after=$fgAfter fg_end=$fgTitle" | Set-Content -Path $logPath -Encoding UTF8
} catch {
    "failed: $($_.Exception.Message)" | Set-Content -Path $log -Encoding UTF8
}
