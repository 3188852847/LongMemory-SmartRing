"""可预测的 Fake LLM，隔离网络和真实模型波动。"""

import re


_CAT_NAME_PATTERN = re.compile(
    r"叫(?P<name>.+?)的猫"
)


class FakeAnswerGenerator:
    """仅用于 V0.1 闭环测试的确定性回答生成器。

    它不是通用语言模型，只支持测试闭环需要的少量行为。
    这样自动化测试不会依赖网络、API Key、模型价格或模型波动。
    """

    def generate(
        self,
        *,
        query: str,
        memory_context: str,
    ) -> str:
        """根据固定规则产生可预测回答。"""

        is_question = query.strip().endswith(("?", "？"))

        # 猫名证据不能回答猫的颜色等其他属性；Fake 也必须拒绝越界推断。
        if is_question and "猫" in query and ("叫什么" in query or "名字" in query):
            match = _CAT_NAME_PATTERN.search(memory_context)

            if match is not None:
                cat_name = match.group("name")
                return f"你的猫叫{cat_name}。"

        if is_question:
            return "我还没有找到相关记忆。"

        return "好的，我记住了。"
