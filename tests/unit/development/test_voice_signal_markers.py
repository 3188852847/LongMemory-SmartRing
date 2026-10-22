"""单轮提示及纯合成数值对齐；无服务、录音、键盘监听或真实语音。"""

import copy
import importlib
import json
import sys
from types import SimpleNamespace
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


def gate_sample(marker, at, *, paired=True, ready=True, active=True, answer=0, first=0,
                generation="a" * 16, mode="adaptive", fallback=0, live=1):
    row = samples(marker)[0]
    row.update(monotonic_before_ms=at - 10, monotonic_after_ms=at)
    row["signal_v2"].update(clock_ms=at - 5, observation_generation=generation)
    row["device"]["ready"] = ready
    row["device"]["cosy_delivery"] = {"state": "configured", "requested_mode": mode,
        "effective_mode": mode, "failure_code": None, "restart_required": False, "outcomes": {"fallback": fallback}}
    row["device"]["voice_interruption"] = {"active_output": active, "counts": {
        "answer_send_returned": answer, "first_answer_send_returned": first, "cue_send_returned": 100,
        "producer_adaptive_buffer": live, "producer_incremental_pcm": 0, "producer_buffered_pcm": 0}}
    if not paired:
        row["signal_v2"]["aec_pairs"] = None
    return row


class Simulation:
    def __init__(self, rows, keys=None):
        self.now, self.rows, self.keys, self.messages = 1000, rows, keys or {}, []

    def read_samples(self):
        return [row for row in self.rows if row["monotonic_after_ms"] <= self.now]

    def read_key(self):
        pending = self.keys.get(self.now, [])
        return pending.pop(0) if pending else None

    def clock(self):
        return self.now, self.now + 100000

    def wait(self, seconds):
        self.now += 100

    def run(self, marker, path, **options):
        return marker.record_gated(path, "not-opened-by-test", read_samples=self.read_samples,
            read_key=self.read_key, clock=self.clock, wait=self.wait, notify=self.messages.append, **options)


def gate_rows(marker):
    rows = [gate_sample(marker, 1000, paired=False, ready=False, active=False),
            gate_sample(marker, 1100, paired=False, active=False),
            gate_sample(marker, 1200),
            gate_sample(marker, 1300, answer=10, first=1),
            gate_sample(marker, 1500, answer=20, first=1),
            gate_sample(marker, 1600, active=False, answer=20, first=1),
            gate_sample(marker, 1800, active=False, answer=20, first=1)]
    rows[1]["device"]["cosy_delivery"]["state"] = "not_observed"
    return rows


def test_gate_discards_early_keys_requires_heard_and_new_start_and_outer_group(marker, tmp_path):
    keys = {1000: ["enter"], 1100: ["heard", "enter"], 1300: ["heard", "enter"],
            1400: ["heard", "enter"], 1500: ["enter"], 1700: ["enter"]}
    sim = Simulation(gate_rows(marker), keys)
    path = tmp_path / "gated.jsonl"
    assert sim.run(marker, path) == "marked_not_audio_verified"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["ready", "speech_start", "speech_end"]
    assert [row["monotonic_ms"] for row in rows] == [1400, 1500, 1700]
    assert sim.now == 1800  # 不因起键后的output=false取消；等到了完整外侧组。
    assert any("丢弃" in value for value in sim.messages)
    assert marker.align(rows, gate_rows(marker))["pair_state"] == "observed"


@pytest.mark.parametrize("mode", ["generation", "disconnected", "fallback", "buffered", "saturated", "output_before_start", "delivery_lost"])
def test_gate_cancels_after_binding_and_does_not_write_start(marker, tmp_path, mode):
    data = gate_rows(marker)
    row = data[4]
    if mode == "generation":
        row["signal_v2"]["observation_generation"] = "b" * 16
    elif mode == "disconnected":
        row["signal_v2"].update(state="no_connection", clock_ms=None, observation_generation=None, aec_pairs=None)
        row["device"]["ready"] = False
    elif mode == "fallback":
        row["device"]["cosy_delivery"]["outcomes"]["fallback"] = 1
    elif mode == "buffered":
        row["device"]["cosy_delivery"]["effective_mode"] = "buffered"
    elif mode == "saturated":
        row["signal_v2"]["aec_pairs"]["total"]["valid"] = marker.LIMIT
    elif mode == "output_before_start":
        row["device"]["voice_interruption"]["active_output"] = False
    else:
        row["device"]["cosy_delivery"]["state"] = "not_observed"
    sim = Simulation(data, {1400: ["heard"], 1500: ["enter"]})
    path = tmp_path / "gated.jsonl"
    assert sim.run(marker, path).startswith("cancelled_")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in records] == ["ready", "cancelled"]


def test_gate_cue_and_producer_start_cannot_arm_and_timeout_is_bounded(marker, tmp_path):
    data = [gate_sample(marker, at) for at in (1000, 1100, 1200, 1300)]
    sim = Simulation(data, {1000: ["heard", "enter"], 1200: ["heard", "enter"]})
    path = tmp_path / "gated.jsonl"
    assert sim.run(marker, path, timeout_seconds=.5) == "cancelled_gate_timeout"
    assert [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines()] == ["cancelled"]


def test_gate_preset_or_warmup_answer_packets_do_not_arm(marker, tmp_path):
    data = [gate_sample(marker, at, answer=index + 1, first=1, live=0)
            for index, at in enumerate((1000, 1100, 1200, 1300))]
    for row in data:
        row["device"]["voice_interruption"]["counts"]["producer_preset"] = 1
    sim = Simulation(data, {1200: ["heard", "enter"]})
    path = tmp_path / "gated.jsonl"
    assert sim.run(marker, path, timeout_seconds=.5) == "cancelled_gate_timeout"
    assert [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines()] == ["cancelled"]


def test_gate_expiration_after_start_cancels_without_synthetic_end(marker, tmp_path):
    data = gate_rows(marker)[:5]
    data.insert(4, gate_sample(marker, 1400, answer=15, first=1))
    sim = Simulation(data, {1400: ["heard"], 1500: ["enter"]})
    path = tmp_path / "gated.jsonl"
    assert sim.run(marker, path, freshness_ms=150) == "cancelled_gate_sample_expired"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in records] == ["ready", "speech_start", "cancelled"]


def test_gate_missing_file_and_processing_pause_do_not_reuse_ready_state(marker):
    first = gate_sample(marker, 1000, answer=1, first=1)
    for missing in (None, []):
        gate = marker._Gate(1000, 3000)
        gate.update([first], 1000, pre_start=True)
        gate.update(missing, 1100, pre_start=True)
        assert gate.reason == "samples_unavailable"
    gate = marker._Gate(1000, 3000)
    gate.update([first], 1000, pre_start=True)
    gate.update([gate_sample(marker, 5000, answer=10, first=1)], 5000, pre_start=True)
    assert gate.reason == "gate_processing_gap_or_clock_rewound"


def test_gate_end_is_not_moved_when_complete_outer_sample_is_missing(marker, tmp_path):
    sim = Simulation(gate_rows(marker)[:-1], {1400: ["heard"], 1500: ["enter"], 1700: ["enter"]})
    path = tmp_path / "gated.jsonl"
    assert sim.run(marker, path, timeout_seconds=2.5) == "cancelled_gate_timeout"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in records] == ["ready", "speech_start", "speech_end", "cancelled"]
    assert records[2]["monotonic_ms"] == 1700
    assert marker.align(records, gate_rows(marker)[:-1])["state"] == "invalid_or_cancelled_marker"


def test_live_tail_uses_complete_lines_only_and_does_not_store_extra_fields(marker, tmp_path):
    path = tmp_path / "samples.jsonl"
    row = gate_sample(marker, 1000)
    path.write_text(json.dumps(row) + '\n{"partial":', encoding="utf-8")
    assert marker._live_samples(path) == [row]
    path.write_text('{"broken-complete":\n', encoding="utf-8")
    assert marker._live_samples(path) is None


def test_record_cli_refuses_missing_samples_before_prompt(marker, tmp_path):
    with pytest.raises(SystemExit):
        marker.main(["record", "--output", str(tmp_path / "must-not-exist.jsonl")])
    assert not (tmp_path / "must-not-exist.jsonl").exists()


def test_console_extended_key_suffix_cannot_become_heard_confirmation(marker, monkeypatch):
    pending = ["\xe0"]
    fake = SimpleNamespace(kbhit=lambda: bool(pending), getwch=lambda: pending.pop(0))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(marker, "_CONSOLE_EXTENDED", False)
    assert marker._console_key() == "other"
    assert marker._console_key() is None
    pending.append("H")  # 箭头键后半码延迟到下一次poll，不能当作H确认。
    assert marker._console_key() == "other"
    pending.extend(["h", "\r", "q"])
    assert [marker._console_key() for _ in range(3)] == ["heard", "enter", "cancel"]


def test_gate_rechecks_latest_file_after_start_key_before_writing_marker(marker, tmp_path):
    sim = Simulation(gate_rows(marker), {1400: ["heard"], 1500: ["enter"]})
    reads_at_start = [0]
    def changed_during_key():
        data = copy.deepcopy(sim.read_samples())
        if sim.now == 1500:
            reads_at_start[0] += 1
            if reads_at_start[0] == 2:
                data[-1]["signal_v2"]["observation_generation"] = "b" * 16
                # 同一查询时间已处理过的行不能合法改写；此处模拟下一组在读键时落地。
                data[-1]["monotonic_before_ms"] += 1
                data[-1]["monotonic_after_ms"] += 1
                data[-1]["signal_v2"]["clock_ms"] += 1
                sim.now += 1
        return data
    path = tmp_path / "gated.jsonl"
    result = marker.record_gated(path, "not-opened", read_samples=changed_during_key,
        read_key=sim.read_key, clock=sim.clock, wait=sim.wait, notify=sim.messages.append)
    assert result == "cancelled_generation_changed"
    assert [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines()] == ["ready", "cancelled"]


def test_gated_paths_and_existing_output_are_protected(marker, tmp_path):
    path = tmp_path / "same.jsonl"
    with pytest.raises(ValueError, match="paths_must_differ"):
        marker.record_gated(path, path)
    assert not path.exists()
    path.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        marker.record_gated(path, tmp_path / "samples.jsonl", read_key=lambda: pytest.fail("no prompt"))
    assert path.read_text(encoding="utf-8") == "preserve"
