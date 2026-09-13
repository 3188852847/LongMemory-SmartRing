"""L1 证据门控的显式包装入口。"""

from longmemory.core.memory.quality.sufficiency_gate_readiness import (
    assess_sufficiency_gate_readiness,
)


def assess_l1_gate_readiness(metrics: dict) -> dict:
    """保留 L1 显式入口，避免调用方将层级传错。"""

    return assess_sufficiency_gate_readiness(metrics, layer="l1")
