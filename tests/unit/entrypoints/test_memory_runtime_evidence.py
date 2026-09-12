from types import SimpleNamespace

from longmemory.application.scenario_recall import ScenarioRecallItem
from longmemory.entrypoints.api.routes.memory_runtime import _retrieval_evidence
from longmemory.methods.contracts import RetrievedTrace


def test_round_screen_receipt_includes_auditable_l2_keyword_score():
    """L2 分数进入回执，但场景正文只留下指纹，不在账本重复保存。"""

    prepared = SimpleNamespace(
        support=SimpleNamespace(retrieved=(
            RetrievedTrace("l1-a", "用户周五答辩。", ("l0-a",), keyword_score=1),
        )),
        scenarios=(ScenarioRecallItem(
            "l2-a", "准备答辩", "用户正在修改 PPT。",
            ("l1-a",), ("l0-a",), keyword_score=4,
        ),),
        personas=(),
    )

    evidence = _retrieval_evidence(prepared)

    assert evidence[1]["layer"] == "l2"
    assert evidence[1]["keyword_score"] == 4
    assert evidence[1]["dense_score"] is None
    assert evidence[1]["fused_score"] is None
    assert "title" not in evidence[1]
    assert "summary" not in evidence[1]
