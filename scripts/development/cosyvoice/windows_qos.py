"""只为当前 CosyVoice 进程明确请求 HighQoS，不修改系统电源或其他进程。

Windows 的掩码 0/0 表示交给系统判断，并不等于明确禁用执行速度节流。
这里按微软文档关闭 EXECUTION_SPEED 节流，保留计时器等其他掩码位；
不提高进程优先级、不固定 CPU、不锁定 GPU 频率，设置随进程退出消失。
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
"""

from __future__ import annotations

import ctypes
import sys


_PROCESS_POWER_THROTTLING = 4
_CURRENT_VERSION = 1
_EXECUTION_SPEED = 0x1


class _PowerThrottlingState(ctypes.Structure):
    # Win32 的 ULONG 固定为 32 位；不用宿主平台的 c_ulong，方便纯替身跨平台测试。
    _fields_ = [("Version", ctypes.c_uint32), ("ControlMask", ctypes.c_uint32),
                ("StateMask", ctypes.c_uint32)]


class _CurrentProcessAPI:
    """只持有 GetCurrentProcess 的伪句柄，不接受 PID，也无需关闭该句柄。"""

    def __init__(self):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetCurrentProcess.argtypes = []
        api.GetCurrentProcess.restype = ctypes.c_void_p
        for name in ("GetProcessInformation", "SetProcessInformation"):
            method = getattr(api, name)
            method.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            method.restype = ctypes.c_int
        self._api = api
        self._handle = api.GetCurrentProcess()

    def read(self):
        state = _PowerThrottlingState(_CURRENT_VERSION, 0, 0)
        if not self._api.GetProcessInformation(
            self._handle, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
        ):
            raise OSError("power_throttling_query_failed")
        return int(state.ControlMask), int(state.StateMask)

    def write(self, control_mask, state_mask):
        state = _PowerThrottlingState(_CURRENT_VERSION, control_mask, state_mask)
        if not self._api.SetProcessInformation(
            self._handle, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
        ):
            raise OSError("power_throttling_set_failed")


def _snapshot(masks):
    if masks is None:
        return None
    return {"control_mask": masks[0], "state_mask": masks[1]}


def _result(applied, reason, before=None, after=None):
    # health 只得到固定状态码和两项系统掩码，不包含异常正文、环境或用户内容。
    return {"applied": applied, "reason": reason,
            "before": _snapshot(before), "after": _snapshot(after)}


def apply_current_process_high_qos(*, platform=None, api=None):
    """在服务启动阶段调用一次；不支持或失败时返回状态，不阻止 TTS 启动。

    无参使用当前 Windows 进程。platform/api 仅用于注入纯测试替身；api
    提供 read() -> (ControlMask, StateMask) 和 write(control, state)。
    applied 表示已读回确认 HighQoS，包括本来就已明确设置的情况。
    """
    if (sys.platform if platform is None else platform) != "win32":
        return _result(False, "not_windows")
    try:
        api = _CurrentProcessAPI() if api is None else api
    except Exception:
        return _result(False, "api_unavailable")
    try:
        before = api.read()
    except Exception:
        return _result(False, "query_failed")
    target = (before[0] | _EXECUTION_SPEED, before[1] & ~_EXECUTION_SPEED)
    if target == before:
        return _result(True, "already_high_qos", before, before)
    try:
        api.write(*target)
    except Exception:
        return _result(False, "set_failed", before)
    try:
        after = api.read()
        if after == target:
            return _result(True, "high_qos_applied", before, after)
    except Exception:
        after = None
    # 不把调用成功当成状态已生效。验证失败时恢复安装前的完整掩码；这不是热切换，
    # 应在模型/请求线程启动前调用，避免和其他运行时的设置修改相互覆盖。
    try:
        api.write(*before)
        after = api.read()
        if after == before:
            return _result(False, "verification_failed_restored", before, after)
    except Exception:
        after = None
    return _result(False, "verification_failed_restore_unconfirmed", before, after)
