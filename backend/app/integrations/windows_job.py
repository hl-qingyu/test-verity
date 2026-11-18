"""Own one suspended process tree; closing its job terminates descendants."""

import ctypes
import os
from ctypes import wintypes


class WindowsJob:
    def __init__(self):
        if os.name != "nt":
            raise OSError("windows_required")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("job_create_failed")

        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION; pointer-sized fields preserve x64 alignment.
        class Basic(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_longlong * 2),
                ("flags", wintypes.DWORD),
                ("min", ctypes.c_size_t),
                ("max", ctypes.c_size_t),
                ("count", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Limits(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise OSError("job_configure_failed")

    def assign_and_resume(self, process):
        # Popen closes the primary thread handle; resume only after job assignment succeeds.
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError("job_assignment_failed")
        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        if resume(int(process._handle)) != 0:
            raise OSError("process_resume_failed")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def assign_pid(self, pid):
        """Attach a ConPTY-owned child before accepting any interactive input."""
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        process = self.kernel.OpenProcess(0x0101, False, pid)
        if not process:
            raise OSError("job_process_open_failed")
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise OSError("job_assignment_failed")
        finally:
            self.kernel.CloseHandle(process)
