"""离线 Smart Turn v3.2 CPU 适配；不下载、不加载 GPU、不接受未核验模型。"""

from pathlib import Path
import hashlib
import math


SOURCE_COMMIT = "4786657e242dfe77dd138699ac564ee074a2a543"
MODEL_REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"
MODEL_FILE = "smart-turn-v3.2-cpu.onnx"
MODEL_SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"
MODEL_SIZE = 8679182
MODEL_URL = f"https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/{MODEL_REVISION}/{MODEL_FILE}"


class SmartTurnCPU:
    """启动阶段显式构造；推理由调用方的单工位预算控制。

    按固定官方 inference.py/audio_utils.py 的处理步骤适配，不 import 会在模块
    顶层隐式建 session 的官方样例。WhisperFeatureExtractor 构造不访问 Hub。
    """

    def __init__(self, model_path):
        path = Path(model_path)
        if path.stat().st_size != MODEL_SIZE:
            raise ValueError("smart_turn_model_size_mismatch")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else self._digest(stream)
        if digest != MODEL_SHA256:
            raise ValueError("smart_turn_model_hash_mismatch")
        import numpy as np
        import onnxruntime as ort
        from transformers import WhisperFeatureExtractor

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(path), sess_options=options,
                                           providers=["CPUExecutionProvider"])
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError("smart_turn_cpu_provider_required")
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].name != "input_features":
            raise ValueError("smart_turn_input_contract_mismatch")
        self.extractor = WhisperFeatureExtractor(chunk_length=8)
        self.np = np

    @staticmethod
    def _digest(stream):
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()

    def predict(self, pcm):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
            raise ValueError("smart_turn_requires_pcm16le")
        np = self.np
        audio = np.frombuffer(pcm[-256000:], dtype="<i2").astype(np.float32) / 32768.0
        audio = np.pad(audio, (128000 - len(audio), 0))
        inputs = self.extractor(audio, sampling_rate=16000, return_tensors="np",
                                padding="max_length", max_length=128000,
                                truncation=True, do_normalize=True)
        features = inputs.input_features.astype(np.float32)
        probability = float(self.session.run(None, {"input_features": features})[0].reshape(-1)[0])
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("smart_turn_invalid_probability")
        return probability
