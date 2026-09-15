"""只用合成数值验证服务端库存估算；不调用 HTTP、模型或设备。"""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "cosyvoice_handoff_benchmark_test",
    ROOT / "scripts/development/cosyvoice/benchmark_handoff.py",
)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_v6_sequential_generation_reconstructs_inventory_and_gaps():
    # 这组公开 V6 数值假设每段在上一段生成后立即开始，首段生成从零计时。
    # 因而可以验证供给递推，但不能把所得缺口称作扬声器测量。
    generation = [2374, 6759, 7704, 6829, 2081]
    playable = [1200, 4500, 4920, 4140, 1320]
    available = 0
    records = []
    for elapsed, audio in zip(generation, playable, strict=True):
        available += elapsed
        records.append({
            "generation_ms": elapsed,
            "available_ms": available,
            "playable_ms": audio,
        })

    result = benchmark.inventory(records)

    assert [r["estimated_gap_before_ms"] for r in records] == [0, 5559, 3204, 1909, 0]
    assert [r["inventory_before_ms"] for r in records] == [0, 0, 0, 0, 2059]
    assert result == {
        "first_available_ms": 2374,
        "max_estimated_gap_ms": 5559,
        "total_estimated_gap_ms": 10672,
        "overall_rtf": 1.6012,
        "estimated_playback_end_ms": 29126,
    }


def test_each_underflow_exhausts_old_inventory_without_carrying_a_negative_balance():
    # 两次连续供给不足后短暂追上，再次不足。历史欠载不能继续扣减新音频库存。
    records = [
        {"generation_ms": generation, "available_ms": available, "playable_ms": 60}
        for generation, available in [(100, 100), (150, 250), (150, 400),
                                      (50, 450), (250, 700), (10, 710)]
    ]

    result = benchmark.inventory(records)

    assert [r["estimated_gap_before_ms"] for r in records] == [0, 90, 90, 0, 180, 0]
    assert [r["inventory_before_ms"] for r in records] == [0, 0, 0, 10, 0, 50]
    assert result["max_estimated_gap_ms"] == 180
    assert result["total_estimated_gap_ms"] == 360
    assert result["estimated_playback_end_ms"] == 820


def test_first_response_wait_is_not_counted_as_between_segment_underflow():
    records = [
        {"generation_ms": 250, "available_ms": 1000, "playable_ms": 120},
        {"generation_ms": 100, "available_ms": 1120, "playable_ms": 60},
    ]

    result = benchmark.inventory(records)

    assert result["first_available_ms"] == 1000
    assert result["max_estimated_gap_ms"] == 0
    assert result["total_estimated_gap_ms"] == 0
    assert result["estimated_playback_end_ms"] == 1180
    # 整体 RTF 按生成耗时计算；available 中额外的准备/间隔不会被伪装成推理时间。
    assert result["overall_rtf"] == 1.9444


@pytest.mark.parametrize("sample_rate,one_packet_frames", [(16000, 960), (24000, 1440),
                                                         (22050, 1323), (44100, 2646)])
def test_sixty_ms_padding_preserves_exact_frames_and_pads_only_the_last_partial_frame(
    sample_rate, one_packet_frames,
):
    assert benchmark.playable_duration_ms(1, sample_rate) == 60
    assert benchmark.playable_duration_ms(one_packet_frames - 1, sample_rate) == 60
    assert benchmark.playable_duration_ms(one_packet_frames, sample_rate) == 60
    assert benchmark.playable_duration_ms(one_packet_frames + 1, sample_rate) == 120
    assert benchmark.playable_duration_ms(one_packet_frames * 82, sample_rate) == 4920
    assert benchmark.playable_duration_ms(one_packet_frames * 82 + 1, sample_rate) == 4980


@pytest.mark.parametrize("frames,sample_rate", [(0, 24000), (-1, 24000), (1440, 0),
                                              (1440, -1), (True, 24000), (1440, True),
                                              (1440.0, 24000), (1440, 24000.0)])
def test_empty_or_invalid_wave_frames_are_rejected(frames, sample_rate):
    with pytest.raises(ValueError, match="invalid_wave_frames"):
        benchmark.playable_duration_ms(frames, sample_rate)


def test_empty_inventory_has_a_clear_failure_instead_of_a_false_success_report():
    with pytest.raises(ValueError, match="audio_inventory_empty_or_invalid"):
        benchmark.inventory([])


@pytest.mark.parametrize("playable", [0, -60, float("nan"), float("inf")])
def test_invalid_audio_inventory_cannot_produce_a_misleading_rtf(playable):
    with pytest.raises(ValueError, match="audio_inventory_empty_or_invalid"):
        benchmark.inventory([{"generation_ms": 100, "available_ms": 100,
                              "playable_ms": playable}])
