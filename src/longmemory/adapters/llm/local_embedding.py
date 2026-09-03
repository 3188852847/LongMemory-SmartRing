"""显式本地 BGE 适配器：只读取固定快照，不在推理时下载/执行远程代码。"""

from importlib.metadata import version
import hashlib
import json
from pathlib import Path

from longmemory.core.memory.retrieval.vector import fingerprint

MODEL_ID = "BAAI/bge-small-zh-v1.5"
REVISION = "7999e1d3359715c523056ef9478215996d62a620"
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
               "special_tokens_map.json", "vocab.txt")
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def snapshot_hashes(directory):
    result = {}
    for name in MODEL_FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("本地模型文件缺失或是符号链接。")
        with path.open("rb") as stream:
            result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


class LocalBGEEncoder:
    def __init__(self, directory: Path):
        directory = directory.resolve()
        receipt = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
        hashes = snapshot_hashes(directory)
        if receipt != {"model": MODEL_ID, "revision": REVISION, "files": hashes}:
            raise ValueError("模型快照与下载校验记录不一致。")
        # 延迟导入：不安装 semantic extra 的 CLI、圆屏和普通测试仍可运行。
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("缺少可选依赖，请安装 semantic extra。") from exc
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
        self._model = AutoModel.from_pretrained(directory, local_files_only=True,
                                               trust_remote_code=False, use_safetensors=True).to("cpu").eval()
        self.metadata = {"provider": "local_bge", "model": MODEL_ID, "revision": REVISION,
                         "files": hashes, "pooling": "cls", "normalization": "l2",
                         "device": "cpu", "dtype": "float32", "max_tokens": 512,
                         "overlength": "reject_not_truncate", "query_prefix": QUERY_PREFIX,
                         "document_prefix": "", "batch_size": 8,
                         "torch": version("torch"), "transformers": version("transformers"),
                         "tokenizers": version("tokenizers"), "safetensors": version("safetensors")}
        self.identity = fingerprint(self.metadata)

    def _encode(self, texts):
        result = []
        for start in range(0, len(texts), 8):
            batch = texts[start:start + 8]
            if any(not isinstance(text, str) or not text.strip() for text in batch):
                raise ValueError("编码文本不能为空。")
            # 不静默截断事实，超出窗口的历史应在另一个版本设计分块策略。
            encoded = self._tokenizer(batch, padding=True, truncation=False, return_tensors="pt")
            if encoded["input_ids"].shape[1] > 512:
                raise ValueError("文本超出 BGE 窗口，本次编码未执行。")
            with self._torch.inference_mode():
                vectors = self._model(**encoded).last_hidden_state[:, 0]
                vectors = self._torch.nn.functional.normalize(vectors, p=2, dim=1)
            result.extend(vectors.cpu().tolist())
        return result

    def encode_documents(self, texts):
        return self._encode(list(texts))

    def encode_query(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("查询不能为空。")
        return self._encode([QUERY_PREFIX + text])[0]
