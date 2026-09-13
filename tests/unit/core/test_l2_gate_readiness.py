from longmemory.core.memory.quality.l2_gate_readiness import assess_l2_gate_readiness


def test_l2_wrapper_cannot_be_mistaken_for_l1():
    result = assess_l2_gate_readiness({})

    assert result["policy_id"] == "l2-sufficiency-controlled-trial-readiness-v1"
    assert result["status"] == "not_ready"
    assert result["automatic_activation"] is False
