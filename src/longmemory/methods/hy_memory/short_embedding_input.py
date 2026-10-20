"""固定SDK的充分条件短路：已证明不会截断的文本不初始化额外tokenizer。"""

from functools import wraps
import hashlib
import inspect
from pathlib import Path
from .observation import span


EMBED_SOURCE_SHA256 = '19a929f5a5c8b2d8c8266a594cc1c1be0ec5861e60b858ca5a380453096cf905'


class ShortEmbeddingInput:
    def __init__(self, module, *, sdk_version, enabled=True):
        self.module = module
        self.original = getattr(module, '_truncate_for_embedding', None)
        self.applied = False
        self.reason = 'disabled'
        self.short_inputs = 0
        self.delegated_inputs = 0
        if not enabled:
            return
        self.reason = 'incompatible'
        path = Path(module.__file__)
        if (sdk_version != '2.0.3' or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != EMBED_SOURCE_SHA256
                or not inspect.isfunction(self.original) or hasattr(self.original, '__wrapped__')
                or Path(self.original.__code__.co_filename).resolve() != path.resolve()
                or module._EMBED_MAX_TOKENS != 8128 or module._CHARS_PER_TOKEN_FALLBACK != 2
                or set(module._TRUNCATION_STATS) != {'calls','truncated','tokens_dropped'}):
            return

        @wraps(self.original)
        def truncate(text, limit=8128):
            with span('embedding_truncate_ms'):
                return self._truncate(text,limit)

        self.wrapped = truncate
        module._truncate_for_embedding = truncate
        self.applied = True
        self.reason = 'proven_utf8_byte_bound'

    def _truncate(self,text,limit):
        module=self.module
        # 一个cl100k普通token至少消耗一个UTF-8字节；原异常分支的字符
        # 估算也不会截断此范围。只跳过必然原样返回的路径，长输入仍用原守卫。
        safe = False
        if type(text) is str and type(limit) is int and limit > 0:
            try:
                safe = len(text.encode('utf-8')) <= limit
            except UnicodeEncodeError:
                pass
        if safe:
            module._TRUNCATION_STATS['calls'] += 1
            self.short_inputs += 1
            return text
        self.delegated_inputs += 1
        return self.original(text, limit)

    def snapshot(self):
        return {'applied': self.applied, 'reason': self.reason,
                'short_inputs': self.short_inputs, 'delegated_inputs': self.delegated_inputs}

    def close(self):
        if self.applied:
            if self.module._truncate_for_embedding is not self.wrapped:
                raise RuntimeError('hy_embedding_wrapper_ownership_changed')
            self.module._truncate_for_embedding = self.original
            self.applied = False
