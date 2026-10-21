"""播放中真实WS上行的隔离反驳场景；合成VAD/ASR，不调用模型或日用服务。"""
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT.parents[2] if ROOT.parent.name == "worktrees" else ROOT
VOICE = MAIN / "local/runtime/xiaozhi-esp32-server/main/xiaozhi-server"
PYTHON = VOICE / ".venv/Scripts/python.exe"


def run_case(case):
    result = subprocess.run([str(PYTHON), "-B", "-X", "utf8", str(ROOT / "tests/fixtures/ad_duplex_probe.py")],
        input=json.dumps(dict(voice=str(VOICE), case=case)).encode(), capture_output=True,
        cwd=ROOT, timeout=18, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")[-5000:]
    return json.loads(result.stdout)


def stages(report, name):
    return [event for event in report["events"] if event["stage"] == name]


def summarize(report):
    mic = stages(report, "synthetic_mic_sent")
    return dict(mode=report["mode"], rate=report.get("rate", 16000),
        stage_counts={name: len(stages(report, name)) for name in (
            "ws_audio_received", "pcm_enqueued", "vad_probe_decision", "asr_receive_audio",
            "asr_model_probe_called", "asr_model_probe_returned", "asr_text_handoff", "wire_interrupt_received")},
        first_input_to_vad_ms=stages(report, "vad_probe_decision")[0]["at_ms"] - stages(report, "synthetic_mic_sent")[0]["at_ms"],
        first_input_to_asr_receive_ms=stages(report, "asr_receive_audio")[0]["at_ms"] - stages(report, "synthetic_mic_sent")[0]["at_ms"],
        max_input_to_ws_ms=max(event["at_ms"] - sent["at_ms"] for event, sent in zip(stages(report, "ws_audio_received"), mic)),
        max_input_to_vad_ms=max(event["at_ms"] - sent["at_ms"] for event, sent in zip(stages(report, "vad_probe_decision"), mic)),
        max_input_queue_depth=max(e["queue_depth"] for e in stages(report, "pcm_enqueued")))


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
@pytest.mark.parametrize("mode,rate", [("buffered", 16000), ("incremental", 16000),
                                      ("adaptive", 16000), ("adaptive", 24000)])
def test_audio_reception_vad_asr_handoff_progress_while_real_output_is_voiced(mode, rate):
    report = run_case(dict(mode=mode, rate=rate))
    assert not report["errors"]
    summary = summarize(report)
    assert summary["stage_counts"] == dict(ws_audio_received=18, pcm_enqueued=18, vad_probe_decision=18,
        asr_receive_audio=18, asr_model_probe_called=1, asr_model_probe_returned=1,
        asr_text_handoff=1, wire_interrupt_received=1)
    assert stages(report, "voiced_output_received")[0]["at_ms"] < stages(report, "synthetic_mic_sent")[0]["at_ms"]
    assert summary["first_input_to_vad_ms"] < 200
    assert summary["first_input_to_asr_receive_ms"] < 200
    assert summary["max_input_to_ws_ms"] < 200 and summary["max_input_to_vad_ms"] < 300
    assert report["wire"]["counts"]["interrupt_sent"] == 1
    assert report["device_interruption_acknowledged"] is False
    print(json.dumps(summary))


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
@pytest.mark.parametrize("negative", ["speech_false", "empty_text"])
def test_absent_subtitle_has_distinct_received_speech_and_asr_explanations(negative):
    report = run_case(dict(mode="adaptive", speech=negative != "speech_false", empty_text=negative == "empty_text"))
    assert len(stages(report, "ws_audio_received")) == 18
    assert len(stages(report, "asr_receive_audio")) == 18
    assert not stages(report, "asr_text_handoff")
    assert not stages(report, "wire_interrupt_received")
    if negative == "speech_false":
        assert all(not event["speech"] for event in stages(report, "vad_probe_decision"))
        assert not stages(report, "asr_model_probe_called")
    else:
        assert len(stages(report, "asr_model_probe_called")) == 1
        assert stages(report, "asr_model_probe_returned")[0]["nonempty"] is False
    print(json.dumps(dict(negative=negative, **summarize(report))))


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
def test_slow_outbound_abort_can_delay_asr_dispatch_without_starving_ws_receipt():
    report = run_case(dict(mode="adaptive", aec=True, slow_output=True))
    assert len(stages(report, "ws_audio_received")) == 18
    summary = summarize(report)
    # 仅发送侧注入350ms背压；原生AEC speech分支await abort再进入ASR.receive_audio。
    assert summary["first_input_to_vad_ms"] < 200
    assert summary["first_input_to_asr_receive_ms"] >= 200
    assert stages(report, "ws_audio_received")[-1]["at_ms"] < stages(report, "asr_receive_audio")[0]["at_ms"]
    assert len(stages(report, "asr_model_probe_called")) == 1
    assert len(stages(report, "asr_text_handoff")) == 1
    assert report["wire"]["counts"]["interrupt_sent"] == 1
    print(json.dumps(dict(synthetic_backpressure_ms=350, **summary)))


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
@pytest.mark.parametrize("voiced_frames", [6, 14])
def test_short_endpoint_can_be_received_and_speech_true_but_skip_formal_asr(voiced_frames):
    report = run_case(dict(mode="adaptive", voiced_frames=voiced_frames))
    assert not report["errors"]
    assert len(stages(report, "ws_audio_received")) == voiced_frames + 1
    assert len(stages(report, "asr_receive_audio")) == voiced_frames + 1
    assert sum(event["speech"] for event in stages(report, "vad_probe_decision")) == voiced_frames
    assert not stages(report, "asr_model_probe_called")
    assert not stages(report, "asr_text_handoff")
    assert not stages(report, "wire_interrupt_received")
    print(json.dumps(dict(short_endpoint_frames=voiced_frames + 1, **summarize(report))))


@pytest.mark.skipif(not PYTHON.is_file(), reason="owner-installed CPU Opus/WS unavailable")
def test_sixteenth_frame_crosses_pinned_asr_endpoint_length_boundary():
    report = run_case(dict(mode="adaptive", voiced_frames=15))
    assert len(stages(report, "ws_audio_received")) == 16
    assert len(stages(report, "asr_model_probe_called")) == 1
    assert stages(report, "asr_model_probe_called")[0]["pcm_bytes"] == 16 * 1920
    assert len(stages(report, "asr_text_handoff")) == 1
    assert len(stages(report, "wire_interrupt_received")) == 1
