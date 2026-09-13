"""L2 证据门控的显式包装入口。"""

from longmemory.core.memory.quality.sufficiency_gate_readiness import (
    assess_sufficiency_gate_readiness,
)


def assess_l2_gate_readiness(metrics: dict) -> dict:
    """固定评估 L2，避免调用方用字符串选择错误的记忆层级。"""

    return assess_sufficiency_gate_readiness(metrics, layer="l2")
