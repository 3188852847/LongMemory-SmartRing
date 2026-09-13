"""L1 证据门控的保守试用就绪度；只做计算，不改变运行策略。"""

from math import pow


POLICY_ID = "l1-sufficiency-controlled-trial-readiness-v1"
MINIMUM_CASES_PER_STRATUM = 60
CONFIDENCE_LEVEL = 0.95


def _zero_error_upper_bound(sample_count: int) -> float | None:
    """0 次失败时的单侧精确二项上界；日常样本仍不一定独立同分布。"""

    if sample_count <= 0:
        return None
    return round(1 - pow(1 - CONFIDENCE_LEVEL, 1 / sample_count), 6)


def assess_sufficiency_gate_readiness(metrics: dict, *, layer: str) -> dict:
    """评估是否只具备“考虑受控试验”的证据，绝不自动启用。"""

    if layer not in {"l1", "l2"}:
        raise ValueError("sufficiency_gate_readiness_layer_invalid")

    answerable = int(metrics.get("answerable_labeled_cases", 0))
    unsupported = int(metrics.get("unsupported_labeled_cases", 0))
    labeled = int(metrics.get("labeled_cases", 0))
    measured = int(metrics.get("context_measured_cases", 0))
    conditions = [
        {"code": "answerable_sample_floor", "passed": answerable >= MINIMUM_CASES_PER_STRATUM,
         "actual": answerable, "required": MINIMUM_CASES_PER_STRATUM},
        {"code": "unsupported_sample_floor", "passed": unsupported >= MINIMUM_CASES_PER_STRATUM,
         "actual": unsupported, "required": MINIMUM_CASES_PER_STRATUM},
        {"code": "zero_false_blocks", "passed": int(metrics.get("false_block_cases", 0)) == 0,
         "actual": int(metrics.get("false_block_cases", 0)), "required": 0},
        {"code": "zero_unsupported_passes",
         "passed": int(metrics.get("unsupported_pass_cases", 0)) == 0,
         "actual": int(metrics.get("unsupported_pass_cases", 0)), "required": 0},
        {"code": "zero_incomplete_allows",
         "passed": int(metrics.get("incomplete_allow_cases", 0)) == 0,
         "actual": int(metrics.get("incomplete_allow_cases", 0)), "required": 0},
        {"code": "all_labeled_context_lengths_measured",
         "passed": labeled > 0 and measured == labeled,
         "actual": measured,
         "required": labeled if labeled else "> 0 exact labels first"},
        {"code": "positive_candidate_reduction",
         "passed": metrics.get("candidate_reduction_rate") is not None
         and metrics["candidate_reduction_rate"] > 0,
         "actual": metrics.get("candidate_reduction_rate"), "required": "> 0"},
    ]
    ready = all(item["passed"] for item in conditions)
    return {
        "policy_id": (
            POLICY_ID if layer == "l1"
            else "l2-sufficiency-controlled-trial-readiness-v1"
        ),
        "status": "ready_for_controlled_trial" if ready else "not_ready",
        "automatic_activation": False,
        "minimum_cases_per_stratum": MINIMUM_CASES_PER_STRATUM,
        "confidence_level": CONFIDENCE_LEVEL,
        "answerable_zero_error_upper_bound": (
            _zero_error_upper_bound(answerable)
            if int(metrics.get("false_block_cases", 0)) == 0
            and int(metrics.get("incomplete_allow_cases", 0)) == 0 else None
        ),
        "unsupported_zero_error_upper_bound": (
            _zero_error_upper_bound(unsupported)
            if int(metrics.get("unsupported_pass_cases", 0)) == 0 else None
        ),
        "conditions": conditions,
        "limitations": [
            "daily_samples_may_not_be_independent_or_identically_distributed",
            "owner_labels_are_not_external_blinded_judgments",
            "readiness_does_not_measure_end_to_end_answer_quality",
            "readiness_never_enables_runtime_policy_automatically",
        ],
    }


def assess_l1_gate_readiness(metrics: dict) -> dict:
    """保留 L1 显式入口，避免调用方将层级传错。"""

    return assess_sufficiency_gate_readiness(metrics, layer="l1")
