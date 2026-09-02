"""固定合成回答回放：不连接模型，不为某个实验组放宽评分标准。"""

import pytest

from longmemory.evaluation.scoring import check_answer


@pytest.mark.parametrize("answer", [
    "抱歉，我没有关于你狗狗名字的任何记忆信息，无法回答这个问题。",
    "抱歉，我没有关于你的猫颜色的信息。如果你告诉我，我可以帮助你记住。",
    "我无法确认猫的颜色。",
    "根据记忆只知道猫叫豆包，但不知道它的颜色。",
    "缺少毛色信息。",
])
def test_unknown_answers_recognize_refusal_variants(answer):
    result = check_answer(answer, abstain=True, answer_contains=None)
    assert result["answer_check_pass"] is True
    assert result["answer_check_reason"] == "refusal_phrase_matched"
    assert result["answer_check_requires_review"] is True


@pytest.mark.parametrize("answer", ["你的猫是黑色的。", "你的猫叫豆包。", "", "好的。"])
def test_unknown_answers_do_not_pass_without_refusal(answer):
    assert not check_answer(answer, abstain=True, answer_contains=None)["answer_check_pass"]


def test_same_answer_uses_same_truth_in_both_groups():
    answer = "没有相关信息，无法回答。"
    assert check_answer(answer, abstain=True, answer_contains=None)["answer_check_pass"]
    assert not check_answer(answer, abstain=False, answer_contains="豆包")["answer_check_pass"]
    assert check_answer("你的猫叫豆包。", abstain=False, answer_contains="豆包")["answer_check_pass"]
