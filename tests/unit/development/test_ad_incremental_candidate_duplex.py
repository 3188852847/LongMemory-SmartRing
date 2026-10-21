"""只新增候选缺口：真实v2封装/固定AEC控制流及故障降级后新轮；不重跑旧矩阵。"""
import json

import pytest

from test_ad_barge_in_duplex import PYTHON, run_case, stages


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
def test_adaptive_v2_duplex_barge_in_retains_mode_and_cleans_reader():
    report = run_case(dict(mode="adaptive", protocol_v2=True, aec=True))
    assert not report["errors"]
    assert len(stages(report, "ws_audio_received")) == 18
    assert len(stages(report, "synthetic_server_aec_called")) == 18
    assert len(stages(report, "asr_text_handoff")) == 1
    assert len(stages(report, "wire_interrupt_received")) == 1
    assert report["delivery"]["effective_mode"] == "adaptive"
    assert report["delivery"]["failure_code"] is None
    assert report["delivery"]["outcomes"]["cancelled"] == 1
    assert all(row["reader_stopped"] for row in report["continuity"])
    print(json.dumps(dict(case="v2_adaptive_cancel", delivery=report["delivery"],
                          received_frames=18, aec_calls=18, device_verified=False)))


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
@pytest.mark.parametrize("mode", ["incremental", "adaptive"])
def test_v2_incomplete_stream_does_not_replay_and_next_turn_is_buffered_complete(mode):
    report = run_case(dict(mode=mode, protocol_v2=True, truncate_once=True, reuse_after_fault=True))
    assert not report["errors"]
    assert report["http_modes"] == ["incremental", "buffered"]
    assert report["delivery"]["requested_mode"] == mode
    assert report["delivery"]["effective_mode"] == "buffered"
    assert report["delivery"]["failure_code"] == "after_handoff"
    assert report["delivery"]["outcomes"]["failed"] == 1
    assert report["delivery"]["outcomes"]["completed"] == 1
    # 16k FIR尾不冲刷；adaptive发现截断后还须丢弃未交付库存，数量受线程交错影响。
    assert 1 <= report["produced_packets"]["old"] <= 9
    assert report["produced_packets"]["candidate-new"] == 60
    assert len(stages(report, "ws_audio_received")) == 18
    assert len(stages(report, "asr_text_handoff")) == 1
    assert len(stages(report, "wire_interrupt_received")) == 1
    assert all(row["reader_stopped"] for row in report["continuity"])
    print(json.dumps(dict(case="v2_fault_recovery", requested=mode,
                          http_modes=report["http_modes"], packets=report["produced_packets"],
                          delivery=report["delivery"], device_verified=False)))
