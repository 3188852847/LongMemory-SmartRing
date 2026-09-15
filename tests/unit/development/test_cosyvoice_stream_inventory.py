"""合成时序验证模型块供给估算；不调用模型、HTTP、设备或个人记忆。"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "cosyvoice_stream_inventory_test",
    ROOT / "scripts/development/cosyvoice/stream_inventory.py",
)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def test_early_first_chunk_does_not_hide_seconds_of_later_underflow():
    result = inventory.estimate_inventory([
        {"at_ms": 800, "audio_ms": 960},
        {"at_ms": 4800, "audio_ms": 1920},
        {"at_ms": 8000, "audio_ms": 120},
    ])

    assert result["first_playback_ms"] == 800
    assert result["max_gap_ms"] == 3040
    assert result["total_gap_ms"] == 4320
    assert result["gap_count"] == 2
    assert result["estimated_end_ms"] == 8120
    assert result["packet_count"] == 50
    assert result["padding_ms"] == 0
    assert [chunk["gap_before_ms"] for chunk in result["chunks"]] == [0, 3040, 1280]


def test_partial_frames_accumulate_across_chunks_and_only_eos_pads():
    result = inventory.estimate_inventory([
        {"at_ms": 100, "audio_ms": 40},
        {"at_ms": 150, "audio_ms": 30},
        {"at_ms": 200, "audio_ms": 50},
        {"at_ms": 250, "audio_ms": 10},
    ])

    assert result["first_available_ms"] == 100
    assert result["first_packet_available_ms"] == result["first_playback_ms"] == 150
    assert result["startup_wait_ms"] == 50
    assert [chunk["released_packet_count"] for chunk in result["chunks"]] == [0, 1, 1, 1]
    assert result["audio_ms"] == 130
    assert result["packet_count"] == 3
    assert result["playable_ms"] == 180
    assert result["padding_ms"] == 50
    assert result["max_gap_ms"] == result["total_gap_ms"] == 0
    assert result["estimated_end_ms"] == 330


@pytest.mark.parametrize("target,start,reason,initial_buffer", [
    (0, 100, "first_packet", 180),
    (180, 100, "buffer_target_reached", 180),
    (360, 900, "buffer_target_reached", 360),
    (600, 1200, "buffer_target_reached", 600),
    (900, 1200, "eos_buffer_fallback", 600),
])
def test_fixed_buffer_starts_only_when_available_frames_meet_target_or_eos_arrives(
    target, start, reason, initial_buffer,
):
    result = inventory.estimate_inventory([
        {"at_ms": 100, "audio_ms": 180},
        {"at_ms": 900, "audio_ms": 180},
        {"at_ms": 1200, "audio_ms": 240},
    ], startup_buffer_ms=target)

    assert result["first_playback_ms"] == start
    assert result["start_reason"] == reason
    assert result["startup_buffer_at_start_ms"] == initial_buffer
    assert result["estimated_end_ms"] == start + 600 + result["total_gap_ms"]
    assert result["total_gap_ms"] == (740 if target <= 180 else 0)


def test_buffer_target_uses_full_frames_not_unpacketized_tail():
    result = inventory.estimate_inventory([
        {"at_ms": 100, "audio_ms": 100},
        {"at_ms": 200, "audio_ms": 20},
        {"at_ms": 250, "audio_ms": 60},
    ], startup_buffer_ms=100)

    assert result["first_playback_ms"] == 200
    assert result["startup_buffer_at_start_ms"] == 120
    assert result["estimated_end_ms"] == 380


def test_fixed_delay_admits_early_arrivals_without_starting_before_deadline():
    result = inventory.estimate_inventory([
        {"at_ms": 100, "audio_ms": 180},
        {"at_ms": 150, "audio_ms": 180},
        {"at_ms": 200, "audio_ms": 240},
    ], startup_buffer_ms=180, startup_delay_ms=240)

    assert result["startup_trigger_ms"] == 100
    assert result["startup_delay_ms"] == 240
    assert result["first_playback_ms"] == 340
    assert result["startup_buffer_at_start_ms"] == 600
    assert not any(chunk["playback_started"] for chunk in result["chunks"])
    assert result["max_gap_ms"] == result["total_gap_ms"] == 0
    assert result["estimated_end_ms"] == 940


def test_fixed_delay_clock_starts_before_future_chunk_and_cannot_hide_underflow():
    result = inventory.estimate_inventory([
        {"at_ms": 100, "audio_ms": 180},
        {"at_ms": 1000, "audio_ms": 180},
    ], startup_buffer_ms=180, startup_delay_ms=120)

    assert result["first_playback_ms"] == 220
    assert result["startup_buffer_at_start_ms"] == 180
    assert result["max_gap_ms"] == result["total_gap_ms"] == 600
    assert result["estimated_end_ms"] == 1180


def test_eos_buffer_fallback_still_applies_the_requested_fixed_delay():
    result = inventory.estimate_inventory(
        [{"at_ms": 100, "audio_ms": 25}],
        startup_buffer_ms=900, startup_delay_ms=120,
    )

    assert result["startup_trigger_ms"] == 100
    assert result["first_playback_ms"] == 220
    assert result["start_reason"] == "eos_buffer_fallback"
    assert result["estimated_end_ms"] == 280


def test_chunk_arriving_exactly_at_start_deadline_is_available_for_initial_playback():
    result = inventory.estimate_inventory([
        {"at_ms": 100, "audio_ms": 60},
        {"at_ms": 220, "audio_ms": 60},
    ], startup_delay_ms=120)

    assert result["first_playback_ms"] == 220
    assert result["startup_buffer_at_start_ms"] == 120
    assert result["estimated_end_ms"] == 340


def test_single_short_chunk_plays_at_eos_even_if_buffer_target_is_unreachable():
    result = inventory.estimate_inventory(
        [{"at_ms": 750, "audio_ms": 25}], startup_buffer_ms=900,
    )

    assert result["first_playback_ms"] == 750
    assert result["first_packet_available_ms"] == 750
    assert result["start_reason"] == "eos_buffer_fallback"
    assert result["packet_count"] == 1
    assert result["padding_ms"] == 35
    assert result["max_gap_ms"] == result["total_gap_ms"] == 0
    assert result["estimated_end_ms"] == 810


def test_chunks_with_no_complete_frame_do_not_end_an_existing_underflow():
    result = inventory.estimate_inventory([
        {"at_ms": 0, "audio_ms": 60},
        {"at_ms": 100, "audio_ms": 10},
        {"at_ms": 200, "audio_ms": 10},
        {"at_ms": 300, "audio_ms": 40},
    ])

    assert [chunk["released_packet_count"] for chunk in result["chunks"]] == [1, 0, 0, 1]
    assert [chunk["gap_before_ms"] for chunk in result["chunks"]] == [0, 0, 0, 240]
    assert result["gap_count"] == 1
    assert result["max_gap_ms"] == result["total_gap_ms"] == 240
    assert result["estimated_end_ms"] == 360


def test_splitting_or_merging_same_time_chunks_does_not_invent_audio_or_packets():
    split = inventory.estimate_inventory([
        {"at_ms": 0, "audio_ms": 20.1},
        {"at_ms": 0, "audio_ms": 19.9},
        {"at_ms": 0, "audio_ms": 20},
        {"at_ms": 30, "audio_ms": 30},
    ])
    merged = inventory.estimate_inventory([
        {"at_ms": 0, "audio_ms": 60},
        {"at_ms": 30, "audio_ms": 30},
    ])

    for field in ("first_playback_ms", "max_gap_ms", "total_gap_ms", "estimated_end_ms",
                  "packet_count", "audio_ms", "playable_ms", "padding_ms"):
        assert split[field] == merged[field]
    assert split["packet_count"] == 2
    assert split["audio_ms"] == 90
    assert split["padding_ms"] == 30


def test_arrival_exactly_when_inventory_finishes_has_no_gap_and_does_not_mutate_input():
    chunks = [{"at_ms": 800, "audio_ms": 960}, {"at_ms": 1760, "audio_ms": 1920}]
    before = copy.deepcopy(chunks)

    result = inventory.estimate_inventory(chunks)

    assert chunks == before
    assert result["max_gap_ms"] == result["total_gap_ms"] == 0
    assert result["estimated_end_ms"] == 3680
    assert result["measurement_scope"] == "model_chunk_availability_estimate_not_speaker_receipt"


@pytest.mark.parametrize("chunks", [
    [], None, {}, [None], [{}], [{"at_ms": 0}], [{"audio_ms": 60}],
    [{"at_ms": 100, "audio_ms": 60}, {"at_ms": 99, "audio_ms": 60}],
])
def test_missing_or_nonmonotonic_chunks_fail(chunks):
    with pytest.raises(ValueError):
        inventory.estimate_inventory(chunks)


@pytest.mark.parametrize("field,invalid", [
    ("at_ms", -1), ("at_ms", float("nan")), ("at_ms", float("inf")),
    ("at_ms", float("-inf")), ("at_ms", True), ("at_ms", "100"),
    ("audio_ms", 0), ("audio_ms", -1), ("audio_ms", float("nan")),
    ("audio_ms", float("inf")), ("audio_ms", False), ("audio_ms", "60"),
])
def test_invalid_numeric_chunk_data_cannot_produce_plausible_metrics(field, invalid):
    chunk = {"at_ms": 0, "audio_ms": 60}
    chunk[field] = invalid
    with pytest.raises(ValueError, match=field):
        inventory.estimate_inventory([chunk])


@pytest.mark.parametrize("target", [-1, float("nan"), float("inf"), True, "180"])
def test_invalid_startup_buffer_fails(target):
    with pytest.raises(ValueError, match="startup_buffer_ms"):
        inventory.estimate_inventory([{"at_ms": 0, "audio_ms": 60}], startup_buffer_ms=target)


@pytest.mark.parametrize("delay", [-1, float("nan"), float("inf"), True, "120"])
def test_invalid_fixed_delay_fails(delay):
    with pytest.raises(ValueError, match="startup_delay_ms"):
        inventory.estimate_inventory([{"at_ms": 0, "audio_ms": 60}], startup_delay_ms=delay)


def test_cli_reads_json_file_and_outputs_machine_readable_estimates(tmp_path, capsys):
    path = tmp_path / "synthetic-chunks.json"
    path.write_text('[{"at_ms": 800, "audio_ms": 960}, {"at_ms": 1800, "audio_ms": 1920}]',
                    encoding="utf-8")

    assert inventory.main([str(path), "--startup-buffer-ms", "180"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["first_playback_ms"] == 800
    assert result["max_gap_ms"] == result["total_gap_ms"] == 40
    assert result["estimated_end_ms"] == 3720
