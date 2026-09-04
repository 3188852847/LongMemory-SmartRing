"""Windows 进程所有权：只结束本启动器创建的任务树，不按名称/PID 批量杀进程。"""

import ctypes
from ctypes import wintypes
import os
import time


class Job:
    """子进程先等待管道许可，加入 Job 后才运行服务，避免后代逃逸窗口。"""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows required")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        api = self.api
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.TerminateJobObject.restype = wintypes.BOOL
        api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                 wintypes.DWORD, ctypes.c_void_p]
        api.QueryInformationJobObject.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                        ("max_working", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", Io), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]

        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise OSError("Cannot establish process ownership")

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            raise OSError("Cannot assign child to job")

    def close(self):
        if self.handle:
            # 等待整棵任务树退出，而不只等待外层 worker；否则端口可能仍短暂占用。
            class Accounting(ctypes.Structure):
                _fields_ = [(name, ctypes.c_int64) for name in
                            ("user", "kernel", "period_user", "period_kernel")] + [
                            (name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")]
            try:
                if not self.api.TerminateJobObject(self.handle, 1):
                    raise OSError("Cannot stop owned job")
                deadline = time.monotonic() + 4
                while True:
                    info = Accounting()
                    if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                        raise OSError("Cannot verify job exit")
                    if info.active == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise OSError("Owned job exit not confirmed")
                    time.sleep(0.02)
            finally:
                self.api.CloseHandle(self.handle)
                self.handle = None
