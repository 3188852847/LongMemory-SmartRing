"""纯合成控制台事件，验证新按键而非字符重复；不读取真实键盘。"""

import ctypes
import importlib
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def marker(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts/development/xiaozhi'))
    return importlib.import_module('voice_signal_markers')


def event(marker, virtual, char='', *, down=True, repeats=1, control=0):
    value = marker._ConsoleRecord()
    value.EventType = 1
    key = value.Event.KeyEvent
    key.bKeyDown, key.wRepeatCount, key.wVirtualKeyCode = down, repeats, virtual
    key.uChar.UnicodeChar = ord(char) if char else 0
    key.dwControlKeyState = control
    return value


def reader(marker, events):
    pending = list(events)
    return marker._ConsoleKeyReader(lambda: pending.pop(0) if pending else None)


def test_windows_console_record_uses_fixed_width_abi(marker):
    assert ctypes.sizeof(marker._ConsoleKeyEvent) == 16
    assert ctypes.sizeof(marker._ConsoleRecord) == 20
    assert marker._ConsoleRecord.Event.offset == 4
    assert marker._ConsoleKeyEvent.uChar.offset == 10
    assert marker._ConsoleKeyEvent.dwControlKeyState.offset == 12


@pytest.mark.parametrize('virtual,char,expected', [(0x48, 'h', 'heard'), (0x0D, '\r', 'enter')])
def test_repeated_downs_require_release_before_new_press(marker, virtual, char, expected):
    keys = reader(marker, [event(marker, virtual, char), event(marker, virtual, char),
        event(marker, virtual, char, repeats=7), event(marker, virtual, char, down=False),
        event(marker, virtual, char)])
    assert [keys.read() for _ in range(5)] == [expected, 'other', 'other', 'other', expected]
    assert keys.read() is None


def test_coalesced_repeats_cannot_become_initial_confirmation(marker):
    keys = reader(marker, [event(marker, 0x48, 'H', repeats=5), event(marker, 0x48, 'H'),
        event(marker, 0x48, 'H', down=False), event(marker, 0x48, 'H')])
    assert [keys.read() for _ in range(4)] == ['other', 'other', 'other', 'heard']


def test_q_ctrl_c_and_modified_h_are_not_confused(marker):
    keys = reader(marker, [event(marker, 0x48, '\b', control=8), event(marker, 0x48, '', down=False),
        event(marker, 0x48, 'H'), event(marker, 0x51, 'Q', repeats=7), event(marker, 0x43, '\x03', control=8)])
    assert [keys.read() for _ in range(5)] == ['other', 'other', 'heard', 'cancel', 'cancel']


def test_numpad_release_cannot_release_a_held_main_enter(marker):
    keys = reader(marker, [event(marker, 0x0D, '\r'), event(marker, 0x0D, '\r', control=0x0100),
        event(marker, 0x0D, '\r', down=False, control=0x0100), event(marker, 0x0D, '\r'),
        event(marker, 0x0D, '\r', down=False), event(marker, 0x0D, '\r')])
    assert [keys.read() for _ in range(6)] == ['enter', 'other', 'other', 'other', 'other', 'enter']


class FakeConsole:
    def __init__(self, events=(), fail=None):
        self.events, self.fail = list(events), fail
    def GetStdHandle(self, kind):
        assert kind == 0xFFFFFFF6
        return 1
    def GetConsoleMode(self, handle, mode):
        return self.fail != 'mode'
    def GetNumberOfConsoleInputEvents(self, handle, count):
        count._obj.value = len(self.events)
        return self.fail != 'count'
    def ReadConsoleInputW(self, handle, target, length, count):
        assert length == 1
        if self.fail == 'read':
            return 0
        value = self.events.pop(0)
        ctypes.memmove(target, ctypes.byref(value), ctypes.sizeof(value))
        count._obj.value = 1
        return 1


def test_console_adapter_reads_local_records_without_changing_mode(marker):
    api = FakeConsole([event(marker, 0x48, 'h')])
    console = marker._WindowsConsoleInput(api)
    assert console.read() == 'heard'
    assert console.read() is None
    # FakeConsole没有模式写入/键盘钩子接口；本路径也不要求它们。


@pytest.mark.parametrize('failure', ['mode', 'count', 'read'])
def test_console_api_failure_is_closed(marker, failure):
    with pytest.raises(OSError, match='console_input_unavailable'):
        marker._WindowsConsoleInput(FakeConsole([event(marker, 0x48, 'h')], fail=failure)).read()


def test_held_early_h_and_start_enter_cannot_confirm_or_end_later(marker, tmp_path):
    fixture = runpy.run_path(str(ROOT / 'tests/unit/development/test_voice_signal_markers.py'))
    data = [fixture['gate_sample'](marker, at, answer=(min(at, 1500) - 900) // 100,
            first=1, active=at < 1600) for at in range(1000, 2100, 100)]
    sim = fixture['Simulation'](data)
    events = {1000: [event(marker, 0x48, 'h')], 1100: [event(marker, 0x48, 'h')],
        1200: [event(marker, 0x48, 'h', repeats=3)], 1300: [event(marker, 0x48, 'h', down=False)],
        1400: [event(marker, 0x48, 'h')],
        1500: [event(marker, 0x48, 'h', down=False), event(marker, 0x0D, '\r')],
        1600: [event(marker, 0x0D, '\r')], 1700: [event(marker, 0x0D, '\r', repeats=4)],
        1800: [event(marker, 0x0D, '\r', down=False)], 1900: [event(marker, 0x0D, '\r')]}
    def read_event():
        pending = events.get(sim.now, [])
        return pending.pop(0) if pending else None
    keys = marker._ConsoleKeyReader(read_event)
    target = tmp_path / 'markers.jsonl'
    assert marker.record_gated(target, 'not-opened', read_samples=sim.read_samples,
        read_key=keys.read, clock=sim.clock, wait=sim.wait, notify=sim.messages.append) == 'marked_not_audio_verified'
    recorded = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines()]
    assert [row['event'] for row in recorded] == ['ready', 'speech_start', 'speech_end']
    assert [row['monotonic_ms'] for row in recorded] == [1400, 1500, 1900]
    assert sim.now == 2000
    assert marker.align(recorded, data)['pair_state'] == 'observed'


@pytest.mark.parametrize('error,reason', [(OSError('not-exported'), 'console_input_unavailable'),
    (KeyboardInterrupt(), 'operator'), (EOFError(), 'operator')])
def test_keyboard_failure_or_interrupt_cancels_without_ungated_fallback(marker, tmp_path, error, reason):
    fixture = runpy.run_path(str(ROOT / 'tests/unit/development/test_voice_signal_markers.py'))
    sim = fixture['Simulation'](fixture['gate_rows'](marker))
    def failed_key():
        raise error
    target = tmp_path / 'cancelled.jsonl'
    result = marker.record_gated(target, 'not-opened', read_samples=sim.read_samples,
        read_key=failed_key, clock=sim.clock, wait=sim.wait, notify=sim.messages.append)
    assert result == 'cancelled_' + reason
    assert [json.loads(line)['event'] for line in target.read_text(encoding='utf-8').splitlines()] == ['cancelled']
    assert 'not-exported' not in target.read_text(encoding='utf-8')
