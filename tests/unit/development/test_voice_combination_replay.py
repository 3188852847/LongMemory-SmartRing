"""组合契约检查器的正反事件回放；不加载真实模型/SDK、不打开网络。"""

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/development/xiaozhi/voice_combination_replay.py"
spec = importlib.util.spec_from_file_location("voice_combination_replay", PATH)
replay = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = replay
spec.loader.exec_module(replay)


def scenario(events, *, name="test"):
    return {"id": name, "condition": "synthetic", "clock_id": "one-clock", "events": events}


def event(name, at, **fields):
    return {"event": name, "at_ms": at, "turn": "t1", "transcript_revision": 1,
            "memory_revision": 1, "audio_epoch": 1, **fields}


def confirmed():
    return [event("turn_started", 0), event("user_end", 10), event("asr_final", 20),
            event("eou_confirmed", 30), event("memory_snapshot", 40)]


def answered():
    return confirmed() + [event("llm_first_text", 50, kind="answer"),
                          event("tts_first_packet", 60, kind="answer"),
                          event("audio_sent", 70, kind="answer")]


def codes(events):
    return [row["code"] for row in replay.replay(scenario(events))["violations"]]


def test_source_is_this_worktree_and_synthetic_suite_matches():
    assert Path(replay.__file__).resolve() == PATH.resolve()
    suite = json.loads(replay.DEFAULT_INPUT.read_text(encoding="utf-8"))
    report = replay.run_suite(suite)
    assert report["matched"]
    assert report["groups"]["cold"] == {"n": 1, "synthetic_send_median_ms": 320}
    assert report["groups"]["hot"] == {"n": 1, "synthetic_send_median_ms": 140}
    assert report["groups"]["synthetic"]["n"] == 0
    assert all(not turn["actual_playback_proven"] for row in report["reports"] for turn in row["turns"])
    assert report["reports"][2]["discarded_candidates"]["known_output_tokens"] == 5
    assert report["reports"][3]["discarded_candidates"]["unknown_output_tokens_count"] == 1


def test_waiting_and_reasoning_never_supply_first_answer_time():
    events = confirmed() + [event("audio_sent", 45, kind="waiting"),
                            event("llm_first_text", 46, kind="reasoning")]
    row = replay.replay(scenario(events))
    assert not row["violations"]
    assert "audio_sent" not in row["turns"][0]["from_user_end_ms"]
    events += [event("llm_first_text", 50, kind="answer"),
               event("tts_first_packet", 60, kind="answer"), event("audio_sent", 70, kind="answer")]
    row = replay.replay(scenario(events))
    assert row["turns"][0]["from_user_end_ms"]["audio_sent"] == 60


@pytest.mark.parametrize("name", ["tts_first_packet", "audio_sent", "playback_observed"])
def test_reasoning_must_not_reach_audio(name):
    assert codes(confirmed() + [event(name, 50, kind="reasoning")]) == ["reasoning_reached_audio"]


@pytest.mark.parametrize("removed", ["asr_final", "eou_confirmed", "memory_snapshot"])
def test_missing_final_confirmation_or_snapshot_rejects_answer(removed):
    events = [item for item in confirmed() if item["event"] != removed]
    assert codes(events + [event("llm_first_text", 50, kind="answer")]) == ["answer_before_confirmation"]


def test_candidate_is_llm_only_until_formal_adoption():
    events = [event("turn_started", 0), event("memory_snapshot", 10),
              event("candidate_started", 20, candidate="c1"),
              event("llm_first_text", 30, kind="answer", candidate="c1"),
              event("candidate_ready", 40, candidate="c1")]
    assert codes(events) == []
    assert "llm_first_text" not in replay.replay(scenario(events))["turns"][0]["from_user_end_ms"]
    assert codes(events + [event("candidate_adopted", 50, candidate="c1")]) == ["candidate_adoption_invalid"]
    assert codes(events + [event("tts_first_packet", 50, candidate="c1", kind="answer")]) == ["answer_before_confirmation"]


@pytest.mark.parametrize("name", ["user_committed", "answer_committed", "tool_effect"])
def test_candidate_has_no_source_memory_or_tool_side_effect(name):
    assert codes(confirmed() + [event(name, 50, actor="candidate")]) == ["candidate_side_effect"]


def test_adoption_and_commit_are_single_use():
    events = confirmed() + [event("candidate_started", 50, candidate="c1"),
                            event("candidate_ready", 60, candidate="c1"),
                            event("candidate_adopted", 70, candidate="c1")]
    assert codes(events + [event("candidate_adopted", 80, candidate="c1")]) == ["candidate_adoption_invalid"]
    assert codes(answered() + [event("answer_committed", 80, actor="formal"),
                              event("answer_committed", 90, actor="formal")]) == ["duplicate_commit"]


def test_adopted_candidate_first_text_is_formal_and_late_cost_is_observation_only():
    events = confirmed() + [event("candidate_started", 50, candidate="c1"),
                            event("candidate_ready", 60, candidate="c1"),
                            event("candidate_adopted", 70, candidate="c1"),
                            event("llm_first_text", 80, candidate="c1", kind="answer"),
                            event("cancelled", 90, audio_epoch=2),
                            event("candidate_cost", 100, candidate="c1", duration_ms=50, output_tokens=5)]
    result = replay.replay(scenario(events))
    assert not result["violations"]
    assert result["cancelled_after_adoption"] == 1
    assert result["discarded_candidates"]["count"] == 0
    assert codes(events + [event("candidate_cost", 110, candidate="c1", output_tokens=5)]) == ["candidate_cost_invalid"]


def test_running_candidate_late_settlement_keeps_unknowns_and_no_audio_permission():
    events = [event("turn_started", 0), event("memory_snapshot", 10),
              event("candidate_started", 20, candidate="c1"), event("cancelled", 30, audio_epoch=2),
              event("candidate_cost", 40, candidate="c1", duration_ms=20)]
    result = replay.replay(scenario(events))
    assert not result["violations"]
    assert result["discarded_candidates"] == {"count": 1, "known_duration_ms": 20,
        "unknown_duration_count": 0, "known_output_tokens": 0, "unknown_output_tokens_count": 1}
    assert codes(events + [event("audio_sent", 50, kind="answer")]) == ["after_cancel"]


def test_resume_discards_candidate_and_resets_timing_origin():
    events = confirmed() + [event("candidate_started", 50, candidate="c1"),
                            event("candidate_ready", 60, candidate="c1", duration_ms=10, output_tokens=4),
                            event("resumed", 70, transcript_revision=2, audio_epoch=2)]
    identity = {"transcript_revision": 2, "audio_epoch": 2}
    events += [event("user_end", 100, **identity), event("asr_final", 110, **identity),
               event("eou_confirmed", 120, **identity), event("memory_snapshot", 130, **identity),
               event("llm_first_text", 140, kind="answer", **identity),
               event("tts_first_packet", 150, kind="answer", **identity),
               event("audio_sent", 160, kind="answer", **identity)]
    result = replay.replay(scenario(events))
    assert not result["violations"]
    assert result["turns"][0]["from_user_end_ms"]["audio_sent"] == 60
    assert result["discarded_candidates"]["count"] == 1
    assert result["discarded_candidates"]["known_duration_ms"] == 10


@pytest.mark.parametrize("name,fields,expected", [
    ("resumed", {"transcript_revision": 2}, "resume_identity_not_advanced"),
    ("memory_changed", {"memory_revision": 2}, "memory_change_not_invalidated"),
    ("cancelled", {}, "cancel_epoch_not_advanced"),
])
def test_invalidation_requires_audio_epoch_advance(name, fields, expected):
    assert codes(confirmed() + [event(name, 50, **fields)]) == [expected]


def test_memory_change_requires_new_snapshot_and_cannot_reuse_ready_audio():
    events = answered() + [event("memory_changed", 80, memory_revision=2, audio_epoch=2)]
    assert codes(events + [event("audio_sent", 90, kind="answer")]) == ["stale_identity"]
    assert codes(events + [event("llm_first_text", 90, kind="answer", memory_revision=2, audio_epoch=2)]) == ["answer_before_confirmation"]
    result = replay.replay(scenario(events))
    assert "audio_sent" not in result["turns"][0]["from_user_end_ms"]


@pytest.mark.parametrize("kind", ["answer", "waiting"])
def test_cancel_and_new_turn_reject_late_packets(kind):
    assert codes(answered() + [event("cancelled", 80, audio_epoch=2),
                              event("audio_sent", 90, kind=kind)]) == ["after_cancel"]
    assert codes(answered() + [event("turn_started", 80, turn="t2"),
                              event("audio_sent", 90, kind=kind)]) == ["turn_superseded"]


def test_send_does_not_prove_device_playback():
    row = replay.replay(scenario(answered()))["turns"][0]
    assert not row["actual_playback_proven"] and not row["synthetic_playback_observed"]
    assert codes(answered() + [event("playback_observed", 80, kind="answer")]) == ["playback_evidence_missing"]
    result = replay.replay(scenario(answered() + [event("playback_observed", 80, kind="answer", evidence="synthetic_device_ack")]))
    assert not result["violations"]
    assert result["turns"][0]["synthetic_playback_observed"]
    assert not result["turns"][0]["actual_playback_proven"]


def test_mixed_clocks_and_reversed_events_are_not_latency_evidence():
    assert codes(confirmed() + [event("llm_first_text", 50, clock_id="other", kind="answer")]) == ["clock_domain_mismatch"]
    assert codes(confirmed() + [event("llm_first_text", 30, kind="answer")]) == ["time_reversed"]
    assert codes(confirmed() + [event("audio_sent", 50, kind="answer")]) == ["stage_predecessor_missing"]


def test_missing_usage_and_cache_counts_stay_unknown():
    result = replay.replay(scenario(confirmed() + [event("usage", 50)]))
    assert result["usage"] == {"samples": 1, "unknown_samples": 1, "cache_reported_samples": 0}
    result = replay.replay(scenario(confirmed() + [event("usage", 50, prompt_tokens=100, output_tokens=1)]))
    assert result["usage"]["cache_reported_samples"] == 0
    assert result["usage"]["unknown_samples"] == 0
    assert codes(confirmed() + [event("usage", 50, prompt_tokens=10, cache_hit_tokens=11)]) == ["cache_usage_invalid"]


@pytest.mark.parametrize("field,value", [("text", "synthetic-private"), ("at_ms", float("nan")),
    ("transcript_revision", True), ("output_tokens", -1), ("event", "unknown")])
def test_invalid_or_body_bearing_events_are_not_echoed(field, value):
    item = event("llm_first_text", 50, kind="answer")
    item[field] = value
    result = replay.replay(scenario(confirmed() + [item]))
    assert result["violations"][-1]["code"] == "event_schema_invalid"
    assert "synthetic-private" not in json.dumps(result)


def test_cli_exit_codes_and_bounded_input(tmp_path, capsys):
    assert replay.main([]) == 0
    assert json.loads(capsys.readouterr().out)["matched"]
    document = {"schema": replay.SCHEMA, "scenarios": [scenario(confirmed() + [event("audio_sent", 50, kind="answer")])]}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert replay.main(["--input", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["mismatched_scenarios"] == ["test"]
    path.write_bytes(b"x" * (replay.MAX_BYTES + 1))
    assert replay.main(["--input", str(path)]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "replay_input_invalid"}


def test_suite_requires_unique_ids_and_does_not_pool_cold_with_hot():
    one = scenario(answered())
    with pytest.raises(ValueError, match="duplicate"):
        replay.run_suite({"schema": replay.SCHEMA, "scenarios": [one, copy.deepcopy(one)]})
    with pytest.raises(ValueError, match="invalid"):
        replay.run_suite({"schema": replay.SCHEMA, "scenarios": []})
    for invalid in ({}, {**one, "events": [event("turn_started", 0)] * 4097}, {**one, "text": "x"}):
        with pytest.raises(ValueError, match="invalid"):
            replay.replay(invalid)
