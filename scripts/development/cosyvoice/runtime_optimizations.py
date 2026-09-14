"""CosyVoice 服务专用、可撤回的推理适配；不修改模型文件或第三方源码。

当前仅适配已核对的 CosyVoice Qwen2Encoder 与 Transformers 4.51.3。
语音 token 解码使用最后一层隐藏状态，原实现却还计算了没有消费者的文本
词表输出。这里绕过该文本输出层，保留相同的 Transformer、注意力掩码、
KV cache（生成时复用的历史状态）及后续语音采样逻辑。
"""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from types import MethodType
from typing import Any


_SUPPORTED_TRANSFORMERS = "4.51.3"
# 此函数体核对自 CosyVoice 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc。
# 比较语法树而非文本，允许换行和注释变化，但上游更改语义后必须重新核对。
_VERIFIED_ONE_STEP_SOURCE = """
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
"""


def _syntax(source: str) -> str:
    return ast.dump(ast.parse(textwrap.dedent(source)), include_attributes=False)


def _is_exact_class(value: Any, module: Any, name: str) -> bool:
    candidate = getattr(module, name, None)
    return candidate is not None and type(value) is candidate


def _compatibility_error(encoder: Any) -> str | None:
    # 不在导入本模块或单元测试时加载 torch/transformers。生产服务必须先加载模型，
    # 再尝试本优化；未知版本、替代模型和缺失依赖一律保留原推理方法。
    transformers = sys.modules.get("transformers")
    if getattr(transformers, "__version__", None) != _SUPPORTED_TRANSFORMERS:
        return "unsupported_transformers_version"
    cosy_module = sys.modules.get("cosyvoice.llm.llm")
    qwen_module = sys.modules.get("transformers.models.qwen2.modeling_qwen2")
    if not _is_exact_class(encoder, cosy_module, "Qwen2Encoder"):
        return "unsupported_encoder_class"
    causal_model = getattr(encoder, "model", None)
    if not _is_exact_class(causal_model, qwen_module, "Qwen2ForCausalLM"):
        return "unsupported_causal_model_class"
    base_model = getattr(causal_model, "model", None)
    if not _is_exact_class(base_model, qwen_module, "Qwen2Model"):
        return "unsupported_base_model_class"
    if getattr(getattr(causal_model, "config", None), "model_type", None) != "qwen2":
        return "unsupported_model_config"
    if any(getattr(module, "training", True) for module in (encoder, causal_model, base_model)):
        return "model_not_in_eval_mode"
    if "forward_one_step" in vars(encoder):
        return "encoder_already_overridden"
    # 跳过有额外行为的包装器会改变输出，所以已有实例改写或 hook 时不安装。
    if "forward" in vars(causal_model):
        return "causal_model_forward_overridden"
    if "forward" in vars(base_model):
        return "base_model_forward_overridden"
    if any(getattr(causal_model, name, None) for name in (
        "_forward_pre_hooks", "_forward_hooks", "_backward_pre_hooks", "_backward_hooks",
    )):
        return "causal_model_has_hooks"
    try:
        source = inspect.getsource(type(encoder).forward_one_step)
        if _syntax(source) != _syntax(_VERIFIED_ONE_STEP_SOURCE):
            return "encoder_forward_contract_changed"
    except (OSError, TypeError, SyntaxError, IndentationError):
        return "encoder_forward_contract_unavailable"
    return None


class Qwen2HiddenOnlyOptimization:
    """一次实例级安装的结果；服务停止推理后可调用 restore 恢复原方法。"""

    def __init__(
        self,
        *,
        applied: bool,
        reason: str,
        encoder: Any = None,
        installed_method: Any = None,
    ) -> None:
        self.applied = applied
        self.reason = reason
        self._encoder = encoder
        self._installed_method = installed_method

    def restore(self) -> bool:
        """仅撤回自己的实例属性，避免覆盖随后安装的其他适配。

        本操作与安装都应在服务加载阶段或无活跃推理时执行，不承诺在生成中
        热切换。删除实例属性后自然恢复上游类的方法，类和其他实例始终不变。
        """
        if not self.applied:
            return False
        if vars(self._encoder).get("forward_one_step") is not self._installed_method:
            self.applied = False
            self.reason = "restore_skipped_method_changed"
            return False
        delattr(self._encoder, "forward_one_step")
        self.applied = False
        self.reason = "restored"
        return True


def install_qwen2_hidden_only(encoder: Any) -> Qwen2HiddenOnlyOptimization:
    """只优化传入的已加载 Qwen2Encoder；不兼容时返回原因并保持原行为。

    生产调用示例：``install_qwen2_hidden_only(cosyvoice.model.llm.llm)``。
    不改权重、精度、采样、声线或训练 forward，也不清除文本词表权重；后者
    仍保留在实例中，以便随时恢复。应由调用方将 applied/reason 放入状态信息。
    """
    error = _compatibility_error(encoder)
    if error is not None:
        return Qwen2HiddenOnlyOptimization(applied=False, reason=error)

    def forward_one_step(self: Any, xs: Any, masks: Any, cache: Any = None):
        # 掩码切片、缓存输入和返回顺序严格保留上游契约。4.51.3 的 Qwen2Model
        # 返回的 last_hidden_state 就是原 hidden_states[-1]，无需保留全部层，
        # 也无需执行 Qwen2ForCausalLM 对 151936 项文本词表的额外矩阵乘法。
        outs = self.model.model(
            inputs_embeds=xs,
            attention_mask=masks[:, -1, :],
            output_hidden_states=False,
            return_dict=True,
            use_cache=True,
            past_key_values=cache,
        )
        return outs.last_hidden_state, outs.past_key_values

    installed_method = MethodType(forward_one_step, encoder)
    encoder.forward_one_step = installed_method
    return Qwen2HiddenOnlyOptimization(
        applied=True,
        reason="qwen2_unused_text_head_bypassed",
        encoder=encoder,
        installed_method=installed_method,
    )
