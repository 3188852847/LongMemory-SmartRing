"""对照固定SDK原截断函数；不导入SDK或初始化任何模型。"""

import ast
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from longmemory.methods.hy_memory.short_embedding_input import ShortEmbeddingInput


ROOT = Path(__file__).resolve().parents[3]
SDK_FILE = ROOT / 'local/runtime/hy-memory/.venv/Lib/site-packages/hy_memory/core/embed_service.py'


@pytest.fixture
def sdk_module():
    if not SDK_FILE.is_file():
        pytest.skip('fixed SDK source is not installed in this worktree')
    tree = ast.parse(SDK_FILE.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == '_truncate_for_embedding')
    def build():
        module = ModuleType('isolated_sdk_truncation')
        module.__file__ = str(SDK_FILE)
        module._EMBED_MAX_TOKENS = 8128
        module._CHARS_PER_TOKEN_FALLBACK = 2
        module._TRUNCATION_STATS = {'calls': 0, 'truncated': 0, 'tokens_dropped': 0}
        module.logger = logging.getLogger('isolated_sdk_truncation')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SDK_FILE), 'exec'), module.__dict__)
        return module
    return build


@pytest.fixture
def encoding(monkeypatch):
    state = SimpleNamespace(calls=0, fail=False)
    class Encoder:
        def encode(self, text):
            return list(text.encode('utf-8'))
        def decode(self, values):
            return bytes(values).decode('utf-8', errors='replace')
    def get_encoding(name):
        assert name == 'cl100k_base'
        state.calls += 1
        if state.fail:
            raise RuntimeError('synthetic unavailable tokenizer')
        return Encoder()
    monkeypatch.setitem(sys.modules, 'tiktoken', SimpleNamespace(get_encoding=get_encoding))
    return state


def outcome(function, text, limit):
    try:
        return ('returned', function(text, limit))
    except Exception as error:
        return ('raised', type(error))


@pytest.mark.parametrize('text', ['', 'hello', '你好，圆屏。', 'Hello，圆屏123', '<|endoftext|>',
                                   'a' * 8128, '中' * 2709 + 'a', '\ud800'])
@pytest.mark.parametrize('unavailable', [False, True])
def test_matches_original_for_short_boundary_empty_and_invalid_unicode(sdk_module, encoding, text, unavailable):
    reference, optimized = sdk_module(), sdk_module()
    encoding.fail = unavailable
    patch = ShortEmbeddingInput(optimized, sdk_version='2.0.3')
    try:
        assert patch.applied
        assert outcome(optimized._truncate_for_embedding, text, 8128) == outcome(reference._truncate_for_embedding, text, 8128)
        assert optimized._TRUNCATION_STATS == reference._TRUNCATION_STATS
        delegated = text == '\ud800'
        assert patch.snapshot()['delegated_inputs'] == int(delegated)
        assert patch.snapshot()['short_inputs'] == int(not delegated)
    finally:
        patch.close()


@pytest.mark.parametrize('text,limit', [('a' * 8129, 8128), ('中' * 2710, 8128),
    ('abc', 0), ('abc', -1), ('abc', None), ('abc', '8'), ('abc', 1.5), ('abc', True),
    (None, 8128), (123, 8128), ('abc', 2)])
@pytest.mark.parametrize('unavailable', [False, True])
def test_unsafe_inputs_and_unusual_limits_keep_original_guard(sdk_module, encoding, text, limit, unavailable):
    reference, optimized = sdk_module(), sdk_module()
    encoding.fail = unavailable
    patch = ShortEmbeddingInput(optimized, sdk_version='2.0.3')
    try:
        assert outcome(optimized._truncate_for_embedding, text, limit) == outcome(reference._truncate_for_embedding, text, limit)
        assert optimized._TRUNCATION_STATS == reference._TRUNCATION_STATS
        assert patch.snapshot()['delegated_inputs'] == 1
        assert patch.snapshot()['short_inputs'] == 0
    finally:
        patch.close()


def test_short_path_never_loads_encoder_and_keeps_original_counters(sdk_module, encoding):
    module = sdk_module()
    original = module._truncate_for_embedding
    patch = ShortEmbeddingInput(module, sdk_version='2.0.3')
    try:
        for text in ('短输入', '<|endoftext|>', 'a' * 8128):
            assert module._truncate_for_embedding(text) is text
        assert encoding.calls == 0
        assert module._TRUNCATION_STATS == {'calls': 3, 'truncated': 0, 'tokens_dropped': 0}
        module._truncate_for_embedding('a' * 8129)
        assert encoding.calls == 1
        assert module._TRUNCATION_STATS == {'calls': 4, 'truncated': 1, 'tokens_dropped': 1}
    finally:
        patch.close()
    assert module._truncate_for_embedding is original
    patch.close()


@pytest.mark.parametrize('change', ['version', 'limit', 'fallback', 'stats', 'filename', 'hash', 'wrapped'])
def test_incompatible_sdk_is_left_untouched(sdk_module, monkeypatch, change):
    from longmemory.methods.hy_memory import short_embedding_input
    module = sdk_module()
    version = '2.0.3'
    if change == 'version':
        version = '2.0.4'
    elif change == 'limit':
        module._EMBED_MAX_TOKENS = 8192
    elif change == 'fallback':
        module._CHARS_PER_TOKEN_FALLBACK = 4
    elif change == 'stats':
        module._TRUNCATION_STATS['unexpected'] = 0
    elif change == 'filename':
        module.__file__ = str(SDK_FILE.with_name('not-installed.py'))
    elif change == 'hash':
        monkeypatch.setattr(short_embedding_input, 'EMBED_SOURCE_SHA256', '0' * 64)
    elif change == 'wrapped':
        module._truncate_for_embedding.__wrapped__ = lambda: None
    original = module._truncate_for_embedding
    patch = ShortEmbeddingInput(module, sdk_version=version)
    assert not patch.applied and patch.reason == 'incompatible'
    assert module._truncate_for_embedding is original
    patch.close()


def test_disabled_mode_and_double_install_do_not_replace_existing_function(sdk_module):
    module = sdk_module()
    original = module._truncate_for_embedding
    disabled = ShortEmbeddingInput(module, sdk_version='2.0.3', enabled=False)
    assert disabled.reason == 'disabled' and not disabled.applied
    assert module._truncate_for_embedding is original
    first = ShortEmbeddingInput(module, sdk_version='2.0.3')
    try:
        second = ShortEmbeddingInput(module, sdk_version='2.0.3')
        assert not second.applied and second.reason == 'incompatible'
        second.close()
        assert module._truncate_for_embedding is first.wrapped
    finally:
        first.close()


def test_close_detects_lost_wrapper_ownership(sdk_module):
    module = sdk_module()
    patch = ShortEmbeddingInput(module, sdk_version='2.0.3')
    module._truncate_for_embedding = lambda text, limit=8128: text
    with pytest.raises(RuntimeError, match='ownership_changed'):
        patch.close()


def test_delegated_exception_is_not_swallowed_and_is_counted(sdk_module, encoding):
    module = sdk_module()
    patch = ShortEmbeddingInput(module, sdk_version='2.0.3')
    try:
        with pytest.raises(TypeError):
            module._truncate_for_embedding('abc', None)
        assert patch.snapshot()['delegated_inputs'] == 1
        assert module._TRUNCATION_STATS['calls'] == 1
    finally:
        patch.close()
