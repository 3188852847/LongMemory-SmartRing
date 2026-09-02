"""判断输入是否值得记忆的基础策略。"""

from longmemory.core.common.text import looks_like_question


class RuleBasedMemoryPolicy:
    """使用简单、可解释规则生成候选记忆内容。

    该策略是 V0.1 的确定性基线，不代表最终的语义提取方案。
    它的作用是先验证完整记忆闭环，并为后续 LLM 提取器提供对照组。
    """

    def extract_contents(self, text: str) -> tuple[str, ...]:
        """从一段原始文本中提取规范化记忆内容。"""

        normalized_text = text.strip()

        # 空输入没有可提取内容。
        if not normalized_text:
            return ()

        # 当前基线不把用户提出的问题保存为长期事实。
        if looks_like_question(normalized_text):
            return ()

        # 当前基线只处理明确的第一人称陈述。
        if not normalized_text.startswith("我"):
            return ()

        # 去掉开头的“我”和结尾标点，再改写为第三人称用户事实。
        statement = normalized_text[1:].strip()
        statement = statement.rstrip("。.!！").strip()

        # 输入只有“我”或者“我。”时，不应生成空记忆。
        if not statement:
            return ()

        return (f"用户{statement}。",)
