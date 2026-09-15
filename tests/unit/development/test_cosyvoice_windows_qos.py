"""仅测试替身 Win32 API；不会改变测试进程或系统的 QoS。"""

import ctypes
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "cosyvoice_windows_qos_test", ROOT / "scripts/development/cosyvoice/windows_qos.py",
)
qos = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qos)


class FakeAPI:
    def __init__(self, control=0, state=0):
        self.masks = (control, state)
        self.writes = []
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.masks

    def write(self, control, state):
        self.writes.append((control, state))
        self.masks = (control, state)


def test_system_managed_state_is_explicitly_changed_to_verified_high_qos():
    api = FakeAPI()
    assert qos.apply_current_process_high_qos(platform="win32", api=api) == {
        "applied": True, "reason": "high_qos_applied",
        "before": {"control_mask": 0, "state_mask": 0},
        "after": {"control_mask": 1, "state_mask": 0},
    }
    assert api.writes == [(1, 0)]
    assert api.reads == 2


@pytest.mark.parametrize("control,state,expected", [(1, 1, (1, 0)), (5, 5, (5, 4)),
                                                   (4, 4, (5, 4)),
                                                   (0x80000004, 0x80000004, (0x80000005, 0x80000004))])
def test_only_execution_speed_changes_and_all_other_bits_survive(control, state, expected):
    api = FakeAPI(control, state)
    result = qos.apply_current_process_high_qos(platform="win32", api=api)
    assert result["applied"] is True
    assert api.writes == [expected]
    assert result["after"] == {"control_mask": expected[0], "state_mask": expected[1]}


def test_already_high_qos_is_idempotent_without_a_system_write():
    api = FakeAPI(5, 4)
    result = qos.apply_current_process_high_qos(platform="win32", api=api)
    assert result["applied"] is True
    assert result["reason"] == "already_high_qos"
    assert result["before"] == result["after"]
    assert api.writes == []


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_non_windows_does_not_load_or_call_native_api(monkeypatch, platform):
    monkeypatch.setattr(qos, "_CurrentProcessAPI", lambda: pytest.fail("must not load Win32"))
    result = qos.apply_current_process_high_qos(platform=platform)
    assert result == {"applied": False, "reason": "not_windows", "before": None, "after": None}


def test_missing_native_api_returns_only_a_fixed_reason(monkeypatch):
    def unavailable():
        raise AttributeError("synthetic confidential exception text")
    monkeypatch.setattr(qos, "_CurrentProcessAPI", unavailable)
    result = qos.apply_current_process_high_qos(platform="win32")
    assert result == {"applied": False, "reason": "api_unavailable", "before": None, "after": None}


def test_failed_query_does_not_overwrite_unknown_masks():
    class Unreadable(FakeAPI):
        def read(self):
            raise OSError("synthetic confidential exception text")
    api = Unreadable()
    result = qos.apply_current_process_high_qos(platform="win32", api=api)
    assert result["reason"] == "query_failed"
    assert not result["applied"]
    assert api.writes == []


def test_failed_set_is_not_reported_as_applied():
    class Unwritable(FakeAPI):
        def write(self, *_args):
            raise OSError("synthetic confidential exception text")
    api = Unwritable(4, 4)
    result = qos.apply_current_process_high_qos(platform="win32", api=api)
    assert result == {"applied": False, "reason": "set_failed",
                      "before": {"control_mask": 4, "state_mask": 4}, "after": None}
    assert api.masks == (4, 4)


@pytest.mark.parametrize("read_raises", [True, False])
def test_failed_verification_restores_original_masks(read_raises):
    class Unverified(FakeAPI):
        def read(self):
            self.reads += 1
            if self.reads == 2:
                if read_raises:
                    raise OSError("synthetic verification failure")
                return (0, 0)
            return self.masks
    api = Unverified(4, 4)
    result = qos.apply_current_process_high_qos(platform="win32", api=api)
    assert result["reason"] == "verification_failed_restored"
    assert not result["applied"]
    assert api.writes == [(5, 4), (4, 4)]
    assert result["before"] == result["after"] == {"control_mask": 4, "state_mask": 4}


def test_failed_restore_is_explicitly_unconfirmed_not_claimed_safe():
    class CannotRestore(FakeAPI):
        def read(self):
            self.reads += 1
            if self.reads > 1:
                raise OSError("synthetic readback failure")
            return self.masks

        def write(self, control, state):
            if self.writes:
                raise OSError("synthetic restore failure")
            super().write(control, state)
    api = CannotRestore()
    result = qos.apply_current_process_high_qos(platform="win32", api=api)
    assert result["reason"] == "verification_failed_restore_unconfirmed"
    assert not result["applied"]
    assert result["after"] is None


def test_win32_structure_keeps_three_32_bit_fields_on_any_test_platform():
    assert ctypes.sizeof(qos._PowerThrottlingState) == 12


def test_native_bridge_uses_only_current_process_and_correct_win32_structure(monkeypatch):
    calls = []
    current_handle = 12345  # 替身伪句柄；测试不加载 kernel32，也不接受外部 PID。

    class Function:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def query(handle, information_class, pointer, size):
        state = ctypes.cast(pointer, ctypes.POINTER(qos._PowerThrottlingState)).contents
        calls.append(("query", handle, information_class, size, state.Version))
        state.ControlMask, state.StateMask = 4, 4
        return 1

    def update(handle, information_class, pointer, size):
        state = ctypes.cast(pointer, ctypes.POINTER(qos._PowerThrottlingState)).contents
        calls.append(("set", handle, information_class, size, state.Version,
                      state.ControlMask, state.StateMask))
        return 1

    class Library:
        GetCurrentProcess = Function(lambda: current_handle)
        GetProcessInformation = Function(query)
        SetProcessInformation = Function(update)

    def load(name, *, use_last_error):
        assert name == "kernel32" and use_last_error is True
        return Library()

    monkeypatch.setattr(qos.ctypes, "WinDLL", load, raising=False)
    api = qos._CurrentProcessAPI()
    assert api.read() == (4, 4)
    api.write(5, 4)
    assert calls == [("query", current_handle, 4, 12, 1),
                     ("set", current_handle, 4, 12, 1, 5, 4)]


@pytest.mark.parametrize("operation", ["read", "write"])
def test_native_zero_return_becomes_a_caught_api_failure(operation):
    class Library:
        def GetProcessInformation(self, *_args):
            return 0

        def SetProcessInformation(self, *_args):
            return 0

    api = object.__new__(qos._CurrentProcessAPI)
    api._api, api._handle = Library(), 12345
    with pytest.raises(OSError, match="power_throttling_"):
        if operation == "read":
            api.read()
        else:
            api.write(1, 0)
