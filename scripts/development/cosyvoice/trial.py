"""独立验证 CosyVoice 3，不读取聊天、密钥或数据库，也不修改当前 TTS。

这个入口故意运行在项目外 CosyVoice 的独立 Python 环境中。它用 LongMemory
已经固定的四条合成文本测量模型加载、首个音频块、完整生成、实时率和显存峰值，
让候选模型进入日常适配层前先经过可比较的本机验证。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import perf_counter
import uuid


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = Path(r"D:\ESP32-Workspace\CosyVoice")
DEFAULT_MODEL = DEFAULT_SOURCE / "pretrained_models" / "Fun-CosyVoice3-0.5B"
REQUIRED_SOURCE = (
    "cosyvoice/cli/cosyvoice.py",
    "third_party/Matcha-TTS",
    "asset/zero_shot_prompt.wav",
)
REQUIRED_MODEL = (
    "cosyvoice3.yaml",
    "llm.pt",
    "flow.pt",
    "hift.pt",
    "campplus.onnx",
    "speech_tokenizer_v3.onnx",
    "CosyVoice-BlankEN",
)
PROMPT_TEXT = (
    "You are a helpful assistant.<|endofprompt|>"
    "希望你以后能够做的比我还好呦。"
)


def validate_local_files(source_root: Path, model_dir: Path) -> dict[str, object]:
    """拒绝隐式联网和半份权重，缺少任何固定输入都在加载 GPU 前失败。"""

    missing_source = [name for name in REQUIRED_SOURCE if not (source_root / name).exists()]
    missing_model = [name for name in REQUIRED_MODEL if not (model_dir / name).exists()]
    if missing_source or missing_model:
        parts = []
        if missing_source:
            parts.append("源码缺失：" + "、".join(missing_source))
        if missing_model:
            parts.append("模型缺失：" + "、".join(missing_model))
        raise ValueError("；".join(parts))
    return {
        "source_root": str(source_root.resolve()),
        "model_dir": str(model_dir.resolve()),
        "prompt_wav": str((source_root / "asset/zero_shot_prompt.wav").resolve()),
    }


def load_cases():
    # 直接复用控制台 TTS 测试台的固定文本，避免候选模型使用更容易的专属样例。
    sys.path.insert(0, str(ROOT / "src"))
    from longmemory.application.voice_benchmark import CASES

    return CASES


def configure_runtime_cache() -> None:
    """把第三方运行缓存限制在项目内的 Git 忽略目录。"""

    runtime_cache = ROOT / "data" / "control" / "cosyvoice-runtime-cache"
    runtime_cache.mkdir(parents=True, exist_ok=True)
    # Windows 上 Numba 默认尝试把编译缓存写回只读的外部 site-packages；其余库也会
    # 使用用户目录。集中到 Git 忽略的项目运行目录，避免修改源码和全局环境。
    os.environ["NUMBA_CACHE_DIR"] = str(runtime_cache / "numba")
    os.environ["MPLCONFIGDIR"] = str(runtime_cache / "matplotlib")
    os.environ["HF_HOME"] = str(runtime_cache / "huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def generate(source_root: Path, model_dir: Path) -> Path:
    paths = validate_local_files(source_root, model_dir)
    # 所有输入均须已在本地存在；模型代码若意外访问 Hugging Face，也会立即失败。
    configure_runtime_cache()
    sys.path.insert(0, str(source_root))
    sys.path.insert(0, str(source_root / "third_party" / "Matcha-TTS"))

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import CosyVoice3

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用；停止而不是悄悄改用 CPU。")

    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    torch.cuda.reset_peak_memory_stats()
    load_started = perf_counter()
    model = CosyVoice3(str(model_dir), fp16=True)
    load_seconds = perf_counter() - load_started

    output = ROOT / "data" / "audio" / ("cosyvoice-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for case in load_cases():
        started = perf_counter()
        first_chunk_seconds = None
        chunks = []
        for item in model.inference_zero_shot(
            case.text,
            PROMPT_TEXT,
            paths["prompt_wav"],
            stream=True,
        ):
            speech = item.get("tts_speech")
            if speech is None or speech.numel() == 0:
                raise RuntimeError(f"{case.id} 返回了空音频块")
            if first_chunk_seconds is None:
                first_chunk_seconds = perf_counter() - started
            chunks.append(speech.detach().cpu())
        completed_seconds = perf_counter() - started
        if not chunks or first_chunk_seconds is None:
            raise RuntimeError(f"{case.id} 没有返回音频")
        waveform = torch.cat(chunks, dim=1)
        if not torch.isfinite(waveform).all():
            raise RuntimeError(f"{case.id} 返回了非有限音频样本")
        audio_seconds = waveform.shape[1] / model.sample_rate
        target = output / f"{case.id}.wav"
        torchaudio.save(str(target), waveform, model.sample_rate)
        records.append(
            {
                "case": case.as_dict(),
                "first_audio_chunk_ms": round(first_chunk_seconds * 1000, 2),
                "completed_ms": round(completed_seconds * 1000, 2),
                "audio_seconds": round(audio_seconds, 4),
                "real_time_factor": round(completed_seconds / audio_seconds, 4),
                "chunk_count": len(chunks),
                "sample_rate_hz": model.sample_rate,
                "output": target.name,
            }
        )

    report = {
        "schema_version": 1,
        "candidate": "Fun-CosyVoice3-0.5B-2512",
        "source_root": paths["source_root"],
        "model_dir": paths["model_dir"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "delivery": "model_native_stream",
        "fp16": True,
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(),
        "model_load_seconds": round(load_seconds, 3),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "randomness": "PyTorch seed 42；不宣称跨平台完全确定",
        "records": records,
        "limitations": [
            "不含 HTTP 适配、Opus 编码、局域网和圆屏扬声器延迟",
            "使用 CosyVoice 仓库自带的合成参考音频，不代表最终定制声线",
            "单轮本机试验不是正式性能结论",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("试听目录：", output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "generate"))
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            print(json.dumps(validate_local_files(args.source_root, args.model_dir), ensure_ascii=False, indent=2))
        else:
            generate(args.source_root, args.model_dir)
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
