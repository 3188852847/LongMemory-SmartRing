"""独立验证 CosyVoice 3，不读取聊天、密钥或数据库，也不修改当前 TTS。

这个入口故意运行在项目外 CosyVoice 的独立 Python 环境中。它用 LongMemory
已经固定的四条合成文本测量模型加载、首个音频块、完整生成、实时率和显存峰值，
让候选模型进入日常适配层前先经过可比较的本机验证。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import wraps
from importlib import import_module
import inspect
import json
import os
from pathlib import Path
import sys
from time import perf_counter
import uuid


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = ROOT / "local/runtime/CosyVoice"
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
WETEXT_MODEL_ID = "pengzhendong/wetext"
WETEXT_REQUIRED_FILES = (
    "en/tn/tagger.fst",
    "en/tn/verbalizer.fst",
    "zh/tn/tagger.fst",
    "zh/tn/verbalizer.fst",
)


def install_modelscope_offline() -> None:
    """只读使用已知的 WeText 缓存，封住本进程的 ModelScope 隐式下载入口。

    已安装的 ModelScope 1.20.0 没有 MODELSCOPE_OFFLINE 开关。它虽然支持
    local_files_only=True，却会先创建临时目录、重写 .mdl，再检查离线分支。
    因此这里直接核对既有 FST 文件，不实例化该库会写入元数据的缓存对象。
    不迁移用户缓存；缺少可选前端时仍由 CosyVoice 原有异常处理决定回退。
    """

    version = import_module("modelscope.version").__version__
    snapshot_module = import_module("modelscope.hub.snapshot_download")
    file_module = import_module("modelscope.hub.file_download")
    file_utils = import_module("modelscope.utils.file_utils")

    def local_path(arguments):
        if version != "1.20.0":
            raise RuntimeError("未经验证的 ModelScope 版本；已拒绝隐式联网。")
        if arguments.get("repo_type") not in (None, "model"):
            raise ValueError("CosyVoice 离线入口不解析 ModelScope 数据集。")
        if arguments.get("repo_id") != WETEXT_MODEL_ID:
            # 主模型已由 validate_local_files 验证本地路径；当前唯一需要从
            # ModelScope 缓存解析的辅助资源是 WeText，未知资源不能自动下载。
            raise ValueError("CosyVoice 离线入口只解析既有 WeText 资源。")
        local_dir = arguments.get("local_dir")
        if local_dir is not None:
            directory = Path(local_dir)
        else:
            cache_dir = arguments.get("cache_dir")
            if cache_dir is None:
                # 保留 ModelScope 原本的 MODELSCOPE_CACHE / 用户缓存选择，
                # 该 API 只计算路径，不创建目录、不读取账号或网络元数据。
                cache_dir = file_utils.get_model_cache_root()
            directory = Path(cache_dir) / WETEXT_MODEL_ID
        if not all((directory / name).is_file() for name in WETEXT_REQUIRED_FILES):
            raise FileNotFoundError("WeText 本地中英文 FST 不完整；已禁止自动下载。")
        file_path = arguments.get("file_path")
        if file_path is not None:
            if file_path not in WETEXT_REQUIRED_FILES:
                raise FileNotFoundError("未验证的 WeText 文件；已禁止自动下载。")
            return str(directory / file_path)
        return str(directory)

    def offline_wrapper(original):
        signature = inspect.signature(original)

        @wraps(original)
        def offline(*args, **kwargs):
            # bind 同时处理位置参数和关键字；即使调用方显式传 False，
            # 也不可能绕过离线规则。不要调用 original，避免缓存写入副作用。
            arguments = signature.bind(*args, **kwargs).arguments
            return local_path(arguments)

        offline._longmemory_offline_only = True
        return offline

    # 公共 snapshot_download / model_file_download 及它们已经被第三方
    # from-import 的别名都会调用这两个模块入口，故无须扫描或改写外部类。
    # 私有入口限于已核对的 1.20.0；未知版本仅保留明确拒绝，不静默联网。
    for module, name in (
        (snapshot_module, "_snapshot_download"),
        (file_module, "_repo_file_download"),
    ):
        original = getattr(module, name, None)
        if not callable(original):
            raise RuntimeError("ModelScope 下载入口不兼容；无法保证离线，停止启动。")
        if not getattr(original, "_longmemory_offline_only", False):
            setattr(module, name, offline_wrapper(original))


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
    """集中可写运行缓存，并在导入 CosyVoice 前安装离线资源保护。"""

    runtime_cache = ROOT / "data" / "control" / "cosyvoice-runtime-cache"
    runtime_cache.mkdir(parents=True, exist_ok=True)
    # Windows 上 Numba 默认尝试把编译缓存写回只读的外部 site-packages；其余库也会
    # 使用用户目录。集中到 Git 忽略的项目运行目录，避免修改源码和全局环境。
    os.environ["NUMBA_CACHE_DIR"] = str(runtime_cache / "numba")
    os.environ["MPLCONFIGDIR"] = str(runtime_cache / "matplotlib")
    os.environ["HF_HOME"] = str(runtime_cache / "huggingface")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    # WeText 属于本项目的语音资源；只对当前语音进程指定缓存根。
    # ModelScope 1.20.0 会在这个根下使用 hub/pengzhendong/wetext。
    # kaldifst 的 Windows 原生读取接口不能打开含中文的绝对文件名。
    # 从项目内部工作目录使用 ASCII 相对路径，实体仍留在项目内；不搬模型、
    # 不创建盘符或联接，也不改全局环境。启动器已固定声音服务的工作目录。
    try:
        wetext_cache = os.path.relpath(ROOT / "local/runtime/modelscope-cache", Path.cwd())
    except ValueError:
        raise RuntimeError("请从智慧圆屏项目内目录启动 CosyVoice，不能跨盘解析 WeText。") from None
    if os.name == "nt" and not wetext_cache.isascii():
        raise RuntimeError("请从智慧圆屏项目根或其英文脚本目录启动 CosyVoice。")
    os.environ["MODELSCOPE_CACHE"] = wetext_cache
    install_modelscope_offline()


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
