"""公开重放工具的边界/取参透明性；不导入模型或接日用服务。"""

import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/development/xiaozhi"))
    value = importlib.import_module("public_aec_replay")
    assert Path(value.__file__).resolve() == ROOT / "scripts/development/xiaozhi/public_aec_replay.py"
    return value


def test_actual_chosen_reference_is_captured_without_changing_result(replay):
    node = ast.parse('''
def _apply_aec(self, timestamp, pcm_frame):
    try:
        best_ts = 20
        best_ref = np.frombuffer(self.aec_audio_cache[best_ts], dtype=np.int16).astype(np.float32)
        n = len(pcm_frame) // 2
        aligned_ref = best_ref[:n]
        if len(aligned_ref) < n:
            aligned_ref = np.pad(aligned_ref, (0, n-len(aligned_ref)))
        return (np.frombuffer(pcm_frame, dtype=np.int16) // 2).astype(np.int16).tobytes()
    except Exception:
        raise
''').body[0]
    captured = []
    first = replay.compile_node(node, {"np": np})
    second = replay.compile_node(replay.instrument_selection(node), {"np": np,
        "_selected_reference": lambda ts, ref: captured.append((ts, ref.copy()))})
    selected = np.array([100, 200], np.int16)
    nearest = np.array([300, 400], np.int16)
    conn = SimpleNamespace(aec_audio_cache={20: selected.tobytes(), 80: nearest.tobytes()})
    pcm = np.array([500, 600, 700], np.int16).tobytes()
    assert first(conn, 80, pcm) == second(conn, 80, pcm)
    assert captured[0][0] == 20  # 真实best_ts，不能偷换为最近timestamp=80。
    np.testing.assert_array_equal(captured[0][1], [100, 200, 0])
    np.testing.assert_array_equal(selected, [100, 200])


def test_unknown_source_shape_is_rejected(replay):
    node = ast.parse('def f():\n    try:\n        return 1\n    except Exception:\n        raise\n').body[0]
    with pytest.raises(ValueError, match="unexpected_aec_selection_shape"):
        replay.instrument_selection(node)


def test_pcm_conversion_rejects_nonfinite_and_clipping(replay):
    for values in (np.array([np.nan]), np.array([32768.]), np.array([-32769.])):
        with pytest.raises(ValueError):
            replay.pcm16(values, np)
    np.testing.assert_array_equal(replay.pcm16(np.array([-32768., 0., 32767.]), np), [-32768, 0, 32767])


def test_wrong_digest_and_existing_result_are_not_overwritten(replay, tmp_path):
    with pytest.raises(ValueError, match="hash_mismatch"):
        replay.checked(b"changed", replay.digest(b"public"))
    path = tmp_path / "summary.json"
    replay.write_json(path, {"state": "first"})
    with pytest.raises(FileExistsError):
        replay.write_json(path, {"state": "second"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "first"}


def test_protocol_is_bounded_and_required_controls_exist(replay):
    assert 4 <= len(replay.CASES) <= 8
    assert replay.FRAME * replay.FRAMES / replay.RATE <= 10
    assert {"near_only", "echo_only", "double_talk_aligned", "double_talk_timestamp_plus120ms"} <= {
        row[0] for row in replay.CASES}
    assert replay.SETTINGS["threshold"] == .5 and replay.SETTINGS["threshold_low"] == .3


def test_over_budget_cli_is_rejected_before_output_creation(replay, tmp_path):
    path = tmp_path / "must-not-create"
    with pytest.raises(SystemExit):
        replay.main(["--output", str(path), "--model", "not-loaded", "--max-seconds", "121"])
    assert not path.exists()


def test_fixed_reset_logger_and_recurrent_state_lifecycle_are_supported(replay):
    node = ast.parse('''
def reset_audio_states(self):
    self.client_audio_buffer.clear()
    self.client_have_voice = False
    self.client_voice_stop = False
    self.client_voice_window.clear()
    self.last_is_voice = False
    self.vad_last_voice_time = 0.0
    self.asr_audio.clear()
    self.logger.bind(tag=TAG).debug("All audio states reset.")
''').body[0]
    warnings = []
    conn = replay.vad_connection(replay.replay_logger(warnings))
    conn.client_audio_buffer.extend(b"xx")
    conn.asr_audio.append(b"xx")
    conn.client_voice_window.append(True)
    recurrent, context = object(), object()
    conn._vad_state, conn._vad_context = recurrent, context
    replay.compile_reset(node)(conn)
    assert not conn.client_audio_buffer and not conn.asr_audio and not conn.client_voice_window
    assert conn._vad_state is recurrent and conn._vad_context is context
    assert warnings == []
