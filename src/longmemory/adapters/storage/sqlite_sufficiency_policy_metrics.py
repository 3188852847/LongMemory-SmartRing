"""按精确人工支持集计算 L1/L2 影子门控代理，不读取正文。"""

from longmemory.core.memory.quality.l1_gate_readiness import (
    assess_sufficiency_gate_readiness,
)


def calculate_policy_metrics(connection, *, layer: str, candidate_id: str) -> dict:
    if layer not in {"l1", "l2"} or candidate_id not in {"memory_id", "scenario_id"}:
        raise ValueError("sufficiency_policy_metrics_layer_invalid")
    prefix = f"{layer}_sufficiency_shadow"
    latest = connection.execute(
        f"SELECT e.id,e.user_message_id,e.support_set_recorded FROM {prefix}_review_events e "
        "JOIN (SELECT user_message_id,max(review_revision) revision "
        f"FROM {prefix}_review_events GROUP BY user_message_id) x "
        "ON x.user_message_id=e.user_message_id AND x.revision=e.review_revision "
        "ORDER BY e.occurred_at,e.id"
    ).fetchall()
    totals = {
        "reviewed_cases": len(latest), "labeled_cases": 0,
        "answerable_labeled_cases": 0, "unsupported_labeled_cases": 0,
        "false_block_cases": 0, "unsupported_pass_cases": 0,
        "incomplete_allow_cases": 0, "overinclusive_allow_cases": 0,
        "original_candidate_count": 0, "kept_candidate_count": 0,
        "true_positive_count": 0, "false_positive_count": 0,
        "missed_support_count": 0, "context_measured_cases": 0,
        "original_context_characters": 0, "kept_context_characters": 0,
    }
    for review in latest:
        if not review["support_set_recorded"]:
            continue
        candidates = connection.execute(
            f"SELECT {candidate_id} item_id,supports_answer,content_characters "
            f"FROM {prefix}_candidates WHERE user_message_id=? ORDER BY rank",
            (review["user_message_id"],),
        ).fetchall()
        expected = {
            row["item_id"] for row in connection.execute(
                f"SELECT {candidate_id} item_id FROM {prefix}_review_supports "
                "WHERE review_event_id=?", (review["id"],),
            ).fetchall()
        }
        predicted = {row["item_id"] for row in candidates if row["supports_answer"] == 1}
        totals["labeled_cases"] += 1
        totals["answerable_labeled_cases" if expected else "unsupported_labeled_cases"] += 1
        totals["false_block_cases"] += bool(expected) and not predicted
        totals["unsupported_pass_cases"] += not expected and bool(predicted)
        totals["incomplete_allow_cases"] += bool(expected and predicted and expected - predicted)
        totals["overinclusive_allow_cases"] += bool(predicted and predicted - expected)
        totals["original_candidate_count"] += len(candidates)
        totals["kept_candidate_count"] += len(predicted)
        totals["true_positive_count"] += len(expected & predicted)
        totals["false_positive_count"] += len(predicted - expected)
        totals["missed_support_count"] += len(expected - predicted)
        if all(row["content_characters"] is not None for row in candidates):
            totals["context_measured_cases"] += 1
            totals["original_context_characters"] += sum(
                row["content_characters"] for row in candidates
            )
            totals["kept_context_characters"] += sum(
                row["content_characters"] for row in candidates if row["item_id"] in predicted
            )
    original = totals["original_candidate_count"]
    original_chars = totals["original_context_characters"]
    predicted_positive = totals["true_positive_count"] + totals["false_positive_count"]
    expected_positive = totals["true_positive_count"] + totals["missed_support_count"]
    totals.update({
        "excluded_latest_reviews": totals["reviewed_cases"] - totals["labeled_cases"],
        "removed_candidate_count": original - totals["kept_candidate_count"],
        "candidate_reduction_rate": None if not original else round(
            (original - totals["kept_candidate_count"]) / original, 6,
        ),
        "context_character_reduction_rate": None if not original_chars else round(
            (original_chars - totals["kept_context_characters"]) / original_chars, 6,
        ),
        "candidate_precision": None if not predicted_positive else round(
            totals["true_positive_count"] / predicted_positive, 6,
        ),
        "candidate_recall": None if not expected_positive else round(
            totals["true_positive_count"] / expected_positive, 6,
        ),
    })
    totals["readiness"] = assess_sufficiency_gate_readiness(totals, layer=layer)
    return totals
