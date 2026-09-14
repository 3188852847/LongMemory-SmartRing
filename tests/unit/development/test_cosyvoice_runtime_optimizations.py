"""用确定性替身验证优化边界与缓存传递，不加载模型、torch 或 CUDA。"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "cosyvoice_runtime_optimizations_test",
    ROOT / "scripts/development/cosyvoice/runtime_optimizations.py",
)
optimizations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(optimizations)


class Mask:
    def __init__(self):
        self.selected = object()
        self.slices = []

    def __getitem__(self, key):
        self.slices.append(key)
        return self.selected


class Qwen2Model:
    training = False

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        # 相同输入和 cache 对应相同确定性输出，让原方法/优化方法的行为可对照。
        state = (kwargs["inputs_embeds"], kwargs["attention_mask"])
        cache = (kwargs["past_key_values"], "next")
        return SimpleNamespace(last_hidden_state=state, hidden_states=(state,), past_key_values=cache)


class Qwen2ForCausalLM:
    training = False
    config = SimpleNamespace(model_type="qwen2")

    def __init__(self):
        self.model = Qwen2Model()
        self.text_head_calls = 0

    def __call__(self, **kwargs):
        self.text_head_calls += 1
        return self.model(**kwargs)


class Qwen2Encoder:
    training = False

    def __init__(self):
        self.model = Qwen2ForCausalLM()

    # 保留已经核实的上游函数体，而不是为替身放宽生产兼容检查。
    def forward_one_step(self, xs, masks, cache=None):
        input_masks = masks[:, -1, :]
        outs = self.model(
            inputs_embeds=xs,
            attention_mask=input_masks,
            output_hidden_states=True,
            return_dict=True,
            use_cache=True,
            past_key_values=cache,
        )
        xs = outs.hidden_states[-1]
        new_cache = outs.past_key_values
        return xs, new_cache


@pytest.fixture
def encoder(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(__version__="4.51.3"))
    monkeypatch.setitem(sys.modules, "cosyvoice.llm.llm", SimpleNamespace(Qwen2Encoder=Qwen2Encoder))
    monkeypatch.setitem(sys.modules, "transformers.models.qwen2.modeling_qwen2", SimpleNamespace(
        Qwen2ForCausalLM=Qwen2ForCausalLM, Qwen2Model=Qwen2Model,
    ))
    return Qwen2Encoder()


def test_hidden_state_and_incremental_cache_match_original_without_text_head(encoder):
    inputs, masks = object(), Mask()
    expected_first = encoder.forward_one_step(inputs, masks)
    expected_second = encoder.forward_one_step(inputs, masks, expected_first[1])
    handle = optimizations.install_qwen2_hidden_only(encoder)
    assert handle.applied and handle.reason == "qwen2_unused_text_head_bypassed"
    first = encoder.forward_one_step(inputs, masks)
    second = encoder.forward_one_step(inputs, masks, first[1])
    assert first == expected_first and second == expected_second
    assert encoder.model.text_head_calls == 2
    assert all(key == (slice(None), -1, slice(None)) for key in masks.slices)
    assert encoder.model.model.calls[-1] == {
        "inputs_embeds": inputs, "attention_mask": masks.selected,
        "output_hidden_states": False, "return_dict": True,
        "use_cache": True, "past_key_values": first[1],
    }


def test_patch_is_instance_local_and_restore_returns_original(encoder):
    other = Qwen2Encoder()
    original_function = Qwen2Encoder.forward_one_step
    handle = optimizations.install_qwen2_hidden_only(encoder)
    assert Qwen2Encoder.forward_one_step is original_function
    assert other.forward_one_step.__func__ is original_function
    duplicate = optimizations.install_qwen2_hidden_only(encoder)
    assert not duplicate.applied and duplicate.reason == "encoder_already_overridden"
    assert not duplicate.restore()
    assert handle.restore() and handle.reason == "restored"
    assert "forward_one_step" not in vars(encoder)
    assert encoder.forward_one_step.__func__ is original_function
    assert not handle.restore()
    assert optimizations.install_qwen2_hidden_only(encoder).applied


def test_restore_preserves_a_later_override(encoder):
    handle = optimizations.install_qwen2_hidden_only(encoder)
    replacement = lambda *_args: "later-adapter"
    encoder.forward_one_step = replacement
    assert not handle.restore()
    assert not handle.applied and handle.reason == "restore_skipped_method_changed"
    assert encoder.forward_one_step is replacement


@pytest.mark.parametrize("change,reason", [
    (lambda e: setattr(e, "training", True), "model_not_in_eval_mode"),
    (lambda e: setattr(e.model.model, "training", True), "model_not_in_eval_mode"),
    (lambda e: setattr(e, "model", object()), "unsupported_causal_model_class"),
    (lambda e: setattr(e.model, "model", object()), "unsupported_base_model_class"),
    (lambda e: setattr(e.model, "config", SimpleNamespace(model_type="other")), "unsupported_model_config"),
    (lambda e: setattr(e.model, "forward", lambda: None), "causal_model_forward_overridden"),
    (lambda e: setattr(e.model.model, "forward", lambda: None), "base_model_forward_overridden"),
    (lambda e: setattr(e.model, "_forward_hooks", {1: object()}), "causal_model_has_hooks"),
])
def test_incompatible_models_remain_unchanged(encoder, change, reason):
    original = encoder.forward_one_step
    change(encoder)
    handle = optimizations.install_qwen2_hidden_only(encoder)
    assert not handle.applied and handle.reason == reason
    assert encoder.forward_one_step == original
    assert "forward_one_step" not in vars(encoder)


def test_unknown_transformers_version_and_encoder_subclass_are_rejected(encoder, monkeypatch):
    monkeypatch.setattr(sys.modules["transformers"], "__version__", "4.51.4")
    handle = optimizations.install_qwen2_hidden_only(encoder)
    assert not handle.applied and handle.reason == "unsupported_transformers_version"
    monkeypatch.setattr(sys.modules["transformers"], "__version__", "4.51.3")

    class DifferentEncoder(Qwen2Encoder):
        pass

    handle = optimizations.install_qwen2_hidden_only(DifferentEncoder())
    assert not handle.applied and handle.reason == "unsupported_encoder_class"


def test_upstream_function_change_is_rejected_without_mutation(encoder, monkeypatch):
    def forward_one_step(self, xs, masks, cache=None):
        return xs, cache

    monkeypatch.setattr(Qwen2Encoder, "forward_one_step", forward_one_step)
    handle = optimizations.install_qwen2_hidden_only(encoder)
    assert not handle.applied and handle.reason == "encoder_forward_contract_changed"
    assert "forward_one_step" not in vars(encoder)


def test_unavailable_source_preserves_original(encoder, monkeypatch):
    def unavailable(_function):
        raise OSError("source unavailable")

    monkeypatch.setattr(optimizations.inspect, "getsource", unavailable)
    handle = optimizations.install_qwen2_hidden_only(encoder)
    assert not handle.applied and handle.reason == "encoder_forward_contract_unavailable"
    assert "forward_one_step" not in vars(encoder)
