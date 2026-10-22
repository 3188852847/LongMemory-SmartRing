"""单轮提示及纯合成数值对齐；无服务、录音、键盘监听或真实语音。"""

import copy
import importlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts/development/xiaozhi"


@pytest.fixture
def marker(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    value = importlib.import_module("voice_signal_markers")
    assert Path(value.__file__).resolve() == SCRIPTS / "voice_signal_markers.py"
    return value


def test_record_only_fixed_markers_and_clocks_no_input_text(marker, tmp_path):
    answers = iter(["never-save-text", "", ""])
    clocks = iter([(10, 1000), (20, 2000), (30, 3000)])
    path = tmp_path / "markers.jsonl"
    assert marker.record(path, ask=lambda prompt: next(answers), clock=lambda: next(clocks)) == "marked_not_audio_verified"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["ready", "speech_start", "speech_end"]
    assert [row["monotonic_ms"] for row in rows] == [10, 20, 30]
    assert "never-save" not in path.read_text(encoding="utf-8")
    assert all(set(row) == {"version", "event", "monotonic_ms", "unix_ms", "timing_kind"} for row in rows)


@pytest.mark.parametrize("answer", ["q", KeyboardInterrupt, EOFError])
def test_cancelled_once_without_test_repetition(marker, tmp_path, answer):
    path = tmp_path / "markers.jsonl"
    def ask(prompt):
        if isinstance(answer, type):
            raise answer()
        return answer
    assert marker.record(path, ask=ask, clock=lambda: (1, 2)) == "cancelled"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["ready", "cancelled"]


def test_existing_output_is_never_overwritten(marker, tmp_path):
    path = tmp_path / "markers.jsonl"
    path.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        marker.record(path, ask=lambda prompt: pytest.fail("must fail before prompt"))
    assert path.read_text(encoding="utf-8") == "preserve"


def samples(marker):
    rows = []
    for index, value in enumerate((10, 20, 30, 40)):
        total = {key: 0 for key in marker.PAIR_KEYS}
        total.update(valid=value, ratio_bins=[0, 0, 0, 0, value, 0])
        rows.append({"sample_index": index, "monotonic_before_ms": value, "monotonic_after_ms": value + 5,
                     "device": {"ready": True, "voice_input_observation": {"counts": {key: value for key in marker.INPUT_KEYS}}},
                     "signal_v2": {"version": 2, "kind": "aec_pairs_supplement", "state": "observed",
                                   "clock_ms": value + 2, "observation_generation": "a" * 16,
                                   "aec_pairs": {"rms_floor_pcm16": 500, "ratio_edges": [.1, .25, .5, .9, 1.1], "total": total}}})
    return rows


def marks():
    return [{"version": 1, "event": event, "monotonic_ms": clock, "unix_ms": 1000 + clock,
             "timing_kind": "manual_outer_bracket_not_exact_voice_boundary"}
            for event, clock in (("ready", 10), ("speech_start", 18), ("speech_end", 37))]


def test_align_outer_request_brackets_and_cumulative_counts(marker):
    value = marker.align(marks(), samples(marker))
    assert value["state"] == "bounded_cumulative_difference_not_voice_verification"
    assert value["sample_before_ms"] == 10 and value["sample_after_ms"] == 45
    assert value["start_uncertainty_ms"] == value["end_uncertainty_ms"] == 8
    assert "input_delta" not in value
    assert value["device_background"]["before"]["counts"] == {key: 10 for key in marker.INPUT_KEYS}
    assert value["device_background"]["after"]["counts"] == {key: 40 for key in marker.INPUT_KEYS}
    assert value["device_background"]["kind"] == "time_nearby_snapshots_not_atomic_or_same_connection_proof"
    assert value["pair_delta"]["valid"] == 30
    assert value["pair_delta"]["ratio_bins"] == [0, 0, 0, 0, 30, 0]
    assert "recent" not in json.dumps(value)


@pytest.mark.parametrize("mode", ["generation", "saturated", "unknown", "decreased", "clock"])
def test_invalid_difference_does_not_invent_zero(marker, mode):
    rows = samples(marker)
    if mode == "generation":
        rows[1]["signal_v2"]["observation_generation"] = "b" * 16
    elif mode == "saturated":
        rows[1]["signal_v2"]["aec_pairs"]["total"]["valid"] = marker.LIMIT
    elif mode == "unknown":
        rows[1]["signal_v2"]["clock_ms"] = None
    elif mode == "decreased":
        rows[1]["device"]["voice_input_observation"]["counts"]["queue_put"] = 1
    else:
        rows[1]["signal_v2"]["clock_ms"] = 1000
    value = marker.align(marks(), rows)
    assert "input_delta" not in value and "pair_delta" not in value


def test_missing_anchors_cancel_and_legacy_samples_do_not_fallback(marker):
    assert marker.align(marks(), [])["state"] == "missing_outer_sample_brackets"
    assert marker.align(marks() + [{"event": "cancelled"}], samples(marker))["state"] == "invalid_or_cancelled_marker"
    rows = samples(marker)
    for row in rows:
        row["signal_v2"] = {"version": 1, "state": "observed"}
    assert marker.align(marks(), rows)["state"] == "missing_outer_sample_brackets"


def test_cli_offline_alignment_exports_only_whitelisted_values(marker, tmp_path):
    a, b, out = (tmp_path / name for name in ("markers.jsonl", "samples.jsonl", "alignment.json"))
    data = samples(marker)
    data[0]["ignored_secret_or_audio"] = "never-save-content"
    a.write_text("\n".join(json.dumps(row) for row in marks()), encoding="utf-8")
    b.write_text("\n".join(json.dumps(row) for row in data), encoding="utf-8")
    marker.main(["align", "--markers", str(a), "--samples", str(b), "--output", str(out)])
    assert "never-save" not in out.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        marker.main(["align", "--markers", str(a), "--samples", str(b), "--output", str(out)])


@pytest.mark.parametrize("mode", ["version", "kind", "extra", "missing", "event", "order", "bool_clock", "missing_ready"])
def test_forged_marker_contract_is_rejected(marker, mode):
    data = marks()
    if mode == "version":
        data[1]["version"] = 2
    elif mode == "kind":
        data[1]["timing_kind"] = "exact_audio_boundary"
    elif mode == "extra":
        data[1]["text"] = "do-not-export"
    elif mode == "missing":
        data[1].pop("unix_ms")
    elif mode == "event":
        data.insert(1, dict(data[0], event="unknown"))
    elif mode == "order":
        data = [data[1], data[0], data[2]]
    elif mode == "bool_clock":
        data[1]["monotonic_ms"] = True
    else:
        data.pop(0)
    value = marker.align(data, samples(marker))
    assert value["state"] == "invalid_or_cancelled_marker"
    assert "input_delta" not in value


@pytest.mark.parametrize("mode", ["missing_pairs", "total_none", "floor", "edges", "extra_signal", "extra_total", "sum"])
def test_public_pair_contract_is_not_silently_accepted(marker, mode):
    data = samples(marker)
    signal = data[1]["signal_v2"]
    if mode == "missing_pairs":
        signal.pop("aec_pairs")
    elif mode == "total_none":
        signal["aec_pairs"]["total"] = None
    elif mode == "floor":
        signal["aec_pairs"]["rms_floor_pcm16"] = 0
    elif mode == "edges":
        signal["aec_pairs"]["ratio_edges"] = [0, .25, .5, .9, 1.1]
    elif mode == "extra_signal":
        signal["extra"] = "do-not-export"
    elif mode == "extra_total":
        signal["aec_pairs"]["total"]["extra"] = 0
    else:
        signal["aec_pairs"]["total"]["valid"] += 1
    result = marker.align(marks(), data)
    assert "pair_delta" not in result or result["pair_delta"] is None
    assert "do-not-export" not in json.dumps(result)


def test_unknown_pair_inside_window_does_not_restore_endpoint_difference(marker):
    data = samples(marker)
    data[1]["signal_v2"]["aec_pairs"] = None
    value = marker.align(marks(), data)
    assert "input_delta" not in value
    assert value["device_background"]["after"]["counts"]["vad_check"] == 40
    assert value["pair_delta"] is None
    assert value["pair_state"] == "unknown_within_window"
    data[0]["signal_v2"]["aec_pairs"] = None
    assert marker.align(marks(), data)["pair_state"] == "baseline_unknown"


@pytest.mark.parametrize("mode", ["overlap", "duplicate", "file_order"])
def test_nonordered_request_brackets_are_rejected(marker, mode):
    data = samples(marker)
    if mode == "overlap":
        data[1]["monotonic_before_ms"] = 12
    elif mode == "duplicate":
        data[1] = copy.deepcopy(data[0])
    else:
        data = [data[0], data[3], data[1], data[2]]
    value = marker.align(marks(), data)
    assert value["state"] == "request_brackets_not_monotonic"
    assert "input_delta" not in value


def test_internal_sampling_gaps_report_actual_intervals_not_fixed_rate(marker):
    data = samples(marker)
    for row, before in zip(data, (10, 20, 200, 400)):
        row["monotonic_before_ms"], row["monotonic_after_ms"] = before, before + 5
        row["signal_v2"]["clock_ms"] = before + 2
    marked = marks()
    marked[-1]["monotonic_ms"] = 397
    value = marker.align(marked, data)
    assert value["sampling"]["sample_count"] == 4
    assert value["sampling"]["max_gap_ms"] == 195
    assert value["sampling"]["total_gap_ms"] == 375
    assert value["sampling"]["kind"] == "between_request_groups_not_audio_loss"
    assert [item["gap_ms"] for item in value["sampling"]["largest_gaps"]] == [195, 175, 5]
