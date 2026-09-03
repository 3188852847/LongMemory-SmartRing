"""跨表示比较使用来源 ID 和答案词面初筛，不比较 L1 文本是否相等。"""

from longmemory.evaluation.scoring import check_answer

SCORER_VERSION = "comparison-lexical-evidence-v1"


def score_evidence(question, support):
    sources = None
    if support.retrieved is not None and all(item.source_event_ids is not None for item in support.retrieved):
        sources = {sid for item in support.retrieved for sid in item.source_event_ids}
    # 多个充分证据集允许重复陈述中的任意一次；跨会话题则要求同一组
    # 所需消息都被召回。未知信息题不以“没有任何召回”作为正确条件。
    evidence_complete = (None if question.abstain or sources is None else
                         any(set(group) <= sources for group in question.evidence_sets))
    return {"evidence_complete": evidence_complete,
            "retrieved_source_ids": sorted(sources) if sources is not None else None}


def score(question, support, answer):
    checks = [check_answer(answer, abstain=question.abstain, answer_contains=term)
              for term in (question.required_terms or (None,))]
    return {**score_evidence(question, support),
            "answer_proxy_pass": all(check["answer_check_pass"] for check in checks),
            "answer_check_reasons": [check["answer_check_reason"] for check in checks],
            "requires_human_review": True}
