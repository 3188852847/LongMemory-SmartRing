from longmemory.core.memory.quality.l1_gate_readiness import assess_l1_gate_readiness


def _metrics(**changes):
    values = {
        "labeled_cases": 120, "answerable_labeled_cases": 60,
        "unsupported_labeled_cases": 60, "false_block_cases": 0,
        "unsupported_pass_cases": 0, "incomplete_allow_cases": 0,
        "context_measured_cases": 120, "candidate_reduction_rate": 0.4,
    }
    values.update(changes)
    return values


def test_readiness_only_allows_considering_a_controlled_trial():
    result = assess_l1_gate_readiness(_metrics())
    assert result["status"] == "ready_for_controlled_trial"
    assert result["automatic_activation"] is False
    assert result["answerable_zero_error_upper_bound"] == 0.048703
    assert all(condition["passed"] for condition in result["conditions"])


def test_readiness_exposes_sample_and_error_failures():
    result = assess_l1_gate_readiness(_metrics(
        labeled_cases=11, answerable_labeled_cases=8,
        unsupported_labeled_cases=3, false_block_cases=1,
        context_measured_cases=10,
    ))
    assert result["status"] == "not_ready"
    assert {item["code"] for item in result["conditions"] if not item["passed"]} == {
        "answerable_sample_floor", "unsupported_sample_floor",
        "zero_false_blocks", "all_labeled_context_lengths_measured",
    }


def test_empty_metrics_never_look_ready():
    result = assess_l1_gate_readiness({})
    assert result["status"] == "not_ready"
    assert result["answerable_zero_error_upper_bound"] is None
    assert result["unsupported_zero_error_upper_bound"] is None
