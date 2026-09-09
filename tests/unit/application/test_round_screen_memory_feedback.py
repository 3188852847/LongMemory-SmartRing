"""圆屏自然反馈分类必须宁可漏掉，也不能把普通对话错当标签。"""

import pytest

from longmemory.application.round_screen_memory_feedback import (
    classify_explicit_round_screen_feedback,
)


@pytest.mark.parametrize("text", [
    "你刚才没想起来我说过的名字。",
    "你刚刚忘了我的猫叫什么",
    "你上一轮没有记起来这件事",
])
def test_explicit_recall_miss(text):
    assert classify_explicit_round_screen_feedback(text) == "recall_miss"


@pytest.mark.parametrize("text", [
    "你刚才记错了。",
    "你上一个回答说错了",
    "你刚刚答错了我的偏好",
])
def test_explicit_wrong_memory(text):
    assert classify_explicit_round_screen_feedback(text) == "wrong_memory"


@pytest.mark.parametrize("text", [
    "我刚才说错了", "这句话错了", "你错了", "他刚才忘了钥匙",
    "我忘了你刚才说什么", "你平时会记错吗", "",
])
def test_ambiguous_text_is_not_feedback(text):
    assert classify_explicit_round_screen_feedback(text) is None
