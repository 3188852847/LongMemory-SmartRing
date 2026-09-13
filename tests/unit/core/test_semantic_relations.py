import json

import pytest

from longmemory.core.memory.quality.semantic_relations import (
    SemanticRelation,
    SemanticRelationError,
    SemanticRelationPair,
    parse_semantic_relation_review,
    validate_semantic_relation_pairs,
)


PAIRS = (
    SemanticRelationPair(
        "pair-home", "memory-a", "memory-b",
        "用户以前住在南京。", "用户现在住在合肥。",
        "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z",
    ),
    SemanticRelationPair(
        "pair-drink", "memory-c", "memory-d",
        "用户喜欢乌龙茶。", "用户也喜欢咖啡。",
        "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z",
    ),
)


def payload(*, second_relation="compatible", second_reason="coexisting_claims"):
    return json.dumps({"schema_version": 1, "decisions": [
        {"pair_id": "pair-home", "relation": "possible_change",
         "reason_code": "explicit_change_over_time", "left_quote": "以前住在南京",
         "right_quote": "现在住在合肥"},
        {"pair_id": "pair-drink", "relation": second_relation,
         "reason_code": second_reason, "left_quote": "喜欢乌龙茶",
         "right_quote": "也喜欢咖啡"},
    ]}, ensure_ascii=False)


def test_parses_complete_ordered_review_without_turning_change_into_conflict():
    result = parse_semantic_relation_review(
        payload(), pairs=PAIRS, reviewer_version="semantic-relation-v1",
    )

    assert result.decisions[0].relation is SemanticRelation.POSSIBLE_CHANGE
    assert result.decisions[1].relation is SemanticRelation.COMPATIBLE


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered", "unknown"])
def test_rejects_missing_extra_reordered_or_unknown_pair_ids(mutation):
    value = json.loads(payload())
    if mutation == "missing":
        value["decisions"].pop()
    elif mutation == "extra":
        value["decisions"].append(dict(value["decisions"][0], pair_id="pair-extra"))
    elif mutation == "reordered":
        value["decisions"].reverse()
    else:
        value["decisions"][0]["pair_id"] = "pair-unknown"

    with pytest.raises(SemanticRelationError, match="semantic_relation_schema_invalid"):
        parse_semantic_relation_review(
            json.dumps(value, ensure_ascii=False), pairs=PAIRS,
            reviewer_version="semantic-relation-v1",
        )


def test_rejects_relation_and_reason_that_do_not_match():
    with pytest.raises(SemanticRelationError, match="semantic_relation_schema_invalid"):
        parse_semantic_relation_review(
            payload(second_relation="possible_conflict", second_reason="coexisting_claims"),
            pairs=PAIRS, reviewer_version="semantic-relation-v1",
        )


def test_rejects_quote_not_present_in_the_supplied_memory():
    value = json.loads(payload())
    value["decisions"][0]["left_quote"] = "用户从未说过的内容"

    with pytest.raises(SemanticRelationError, match="semantic_relation_schema_invalid"):
        parse_semantic_relation_review(
            json.dumps(value, ensure_ascii=False), pairs=PAIRS,
            reviewer_version="semantic-relation-v1",
        )


def test_rejects_duplicate_pair_identity_before_any_model_call():
    with pytest.raises(SemanticRelationError, match="semantic_relation_pair_id_duplicate"):
        validate_semantic_relation_pairs((PAIRS[0], PAIRS[0]))
