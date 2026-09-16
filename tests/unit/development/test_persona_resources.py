"""只检查人格资源的结构，不把词面检查当作模型行为/还原质量评估。"""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[3]
PERSONAS = ROOT / 'src/longmemory/prompts/personas'


@pytest.mark.parametrize('name', ['elysia_v1.txt', 'plain_v1.txt'])
def test_persona_has_one_replaceable_memory_slot(name):
    text = (PERSONAS / name).read_text(encoding='utf-8')
    assert text.count('<memory>') == text.count('</memory>') == 1
    rendered = re.sub(r'<memory>.*?</memory>', '<memory>合成记忆</memory>', text, flags=re.DOTALL)
    assert '合成记忆' in rendered
    # 不把之前猫名验收答案偷偷塞进人格，否则可能把角色提示记忆误判成召回。
    assert '豆包' not in text


def test_elysia_attribution_and_explicit_limits_exist():
    license_text = (ROOT / 'docs/third_party/elysia-skill-LICENSE.txt').read_text(encoding='utf-8')
    assert 'Copyright (c) 2026 jtydyb-sha' in license_text
    text = (PERSONAS / 'elysia_v1.txt').read_text(encoding='utf-8')
    assert 'AI 角色扮演助手' in text
    assert '没有依据时明确说不知道' in text
    assert '角色配置本身不授予联网搜索' in text
    assert '若本轮系统实际提供搜索或其他工具' in text
