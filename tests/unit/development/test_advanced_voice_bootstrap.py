"""公共启动接线：关闭无模型导入，缺资源降级，正式端点需真实验收门。"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from contextvars import ContextVar
from threading import Lock

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts/development/xiaozhi"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("ai_advanced_bootstrap", SCRIPTS / "launch_with_memory.py")
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


def classes():
    class Connection:
        def reset_audio_states(self):
            pass

        async def close(self):
            pass

    class ASR:
        async def receive_audio(self, connection, frame, have_voice):
            pass
    return Connection, ASR


def test_defaults_do_not_import_or_construct_detector_and_keep_buffered():
    connection, asr = classes()
    def forbidden(_path):
        raise AssertionError("off must never load models")
    result = launch.install_advanced_voice_policy(connection, detector_factory=forbidden, asr_provider_class=asr)
    assert result["turn_end"] == {"requested": "off", "mode": "off", "installed": False, "reason": "disabled"}
    assert connection._longmemory_cosy_delivery_mode == "buffered"
    assert not hasattr(asr, "_longmemory_turn_end_installed")


def test_unverified_enabled_does_not_load_or_claim_calibration():
    connection, asr = classes()
    def forbidden(_path):
        raise AssertionError("unverified enabled must not load")
    result = launch.install_advanced_voice_policy(connection, turn_end_mode="enabled", turn_end_model="synthetic",
                                                  asr_provider_class=asr, detector_factory=forbidden)
    assert result["turn_end"]["reason"] == "calibration_required"
    assert result["turn_end"]["mode"] == "off"


@pytest.mark.parametrize("error", [FileNotFoundError("private"), ImportError("private"), ValueError("private")])
def test_missing_or_invalid_model_is_unavailable_without_exception_leak(error):
    connection, asr = classes()
    def factory(_path):
        raise error
    result = launch.install_advanced_voice_policy(connection, turn_end_mode="shadow", turn_end_model="synthetic",
                                                  asr_provider_class=asr, detector_factory=factory)
    assert result["turn_end"]["reason"] == "model_unavailable"
    assert "private" not in repr(result)


@pytest.mark.parametrize("mode,approved", [("shadow", False), ("enabled", True)])
def test_real_turn_installer_receives_explicit_mode_and_callback(mode, approved):
    connection, asr = classes()
    result = launch.install_advanced_voice_policy(connection, turn_end_mode=mode, turn_end_model="synthetic",
        asr_provider_class=asr, detector_factory=lambda _: SimpleNamespace(predict=lambda _pcm: .8),
        on_turn_event=lambda *_args: None, calibration_approved=approved, cosy_delivery_mode="adaptive")
    assert result["turn_end"]["mode"] == mode and result["turn_end"]["installed"]
    assert asr._longmemory_turn_end_installed
    assert connection._longmemory_cosy_delivery_mode == "adaptive"
    assert result["cosy"]["actual_playback_proven"] is False


@pytest.mark.parametrize("options", [{"turn_end_mode": "bad"}, {"cosy_delivery_mode": "bad"}])
def test_invalid_selection_rejected_before_mutation(options):
    connection, _ = classes()
    with pytest.raises(ValueError):
        launch.install_advanced_voice_policy(connection, **options)
    assert not hasattr(connection, "_longmemory_cosy_delivery_mode")


def test_live_reinstallation_requires_restart():
    connection, _ = classes()
    launch.install_advanced_voice_policy(connection)
    with pytest.raises(RuntimeError, match="restart_required"):
        launch.install_advanced_voice_policy(connection, cosy_delivery_mode="adaptive")
    assert connection._longmemory_cosy_delivery_mode == "buffered"


def test_formal_metadata_uses_this_context_not_other_pending_round_or_fixed_reply():
    context = ContextVar("synthetic-formal-key", default="a"*32)
    one = {"memory_protocol": 2, "client_round_id": "a"*32,
           "turn_id": "11111111-1111-4111-8111-111111111111"}
    memory = SimpleNamespace(_turn_key=context, _lock=Lock(), _session_id="b"*32,
        _pending_completions={"a"*32: one, "c"*32: {"PRIVATE": "must-not-return"}})
    connection = SimpleNamespace(memory=memory)
    assert launch.voice_proposal_formal_metadata(connection) == {
        "formal_turn_id": one["turn_id"], "client_round_id": "a"*32, "session_id": "b"*32}
    with memory._lock:
        assert launch.voice_proposal_formal_metadata(connection) is None
    one["fixed_reply"] = "合成预算/管理回复"
    assert launch.voice_proposal_formal_metadata(connection) is None
    one.pop("fixed_reply")
    token = context.set("c"*32)
    try:
        assert launch.voice_proposal_formal_metadata(connection) is None
    finally:
        context.reset(token)
