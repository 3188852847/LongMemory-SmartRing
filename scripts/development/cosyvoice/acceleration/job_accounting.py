"""只查询调用方已拥有的Windows Job句柄；不申请结束外部进程的权限。"""

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone


class BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IOCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class BasicAccounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")]+[(name, wintypes.DWORD) for name in ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]


class AccountingAndIO(ctypes.Structure):
    _fields_ = [("BasicInfo", BasicAccounting), ("IoInfo", IOCounters)]


def read_job_snapshot(handle):
    """JOB_OBJECT_QUERY接口；峰值是提交内存，不是工作集或已证实的失败原因。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    limits, counters = ExtendedLimits(), AccountingAndIO()
    for kind, value in ((9, limits), (8, counters)):
        if not kernel.QueryInformationJobObject(handle, kind, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
    basic, io = counters.BasicInfo, counters.IoInfo
    return dict(captured_at_utc=datetime.now(timezone.utc).isoformat(),
                peak_job_memory_bytes=limits.PeakJobMemoryUsed, peak_process_memory_bytes=limits.PeakProcessMemoryUsed,
                process_memory_limit_bytes=limits.ProcessMemoryLimit, job_memory_limit_bytes=limits.JobMemoryLimit,
                limit_flags=limits.BasicLimitInformation.LimitFlags, affinity_mask=limits.BasicLimitInformation.Affinity,
                active_processes=basic.ActiveProcesses, total_processes=basic.TotalProcesses,
                terminated_processes=basic.TotalTerminatedProcesses, cpu_user_time_100ns=basic.TotalUserTime,
                cpu_kernel_time_100ns=basic.TotalKernelTime, page_fault_count=basic.TotalPageFaultCount,
                io_read_bytes=io.ReadTransferCount, io_write_bytes=io.WriteTransferCount,
                io_read_operations=io.ReadOperationCount, io_write_operations=io.WriteOperationCount,
                memory_failure_cause_proven=False)
