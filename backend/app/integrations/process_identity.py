"""Process lifetime identity for conservative local reservation recovery."""

import ctypes
import json
import os
import socket
from ctypes import wintypes
from pathlib import Path


def _started(pid: int) -> str | None:
    if os.name != "nt":
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[19]
        except FileNotFoundError:
            return "gone"
        except (OSError, IndexError):
            return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return "gone" if ctypes.get_last_error() == 87 else None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def current_identity() -> str:
    return json.dumps([socket.gethostname(), os.getpid(), _started(os.getpid())])


def proven_exited(identity: str) -> bool:
    try:
        host, pid, started = json.loads(identity)
        if host != socket.gethostname() or type(pid) is not int or not started:
            return False
        actual = _started(pid)
        return actual is not None and actual != started
    except (ValueError, TypeError):
        return False
