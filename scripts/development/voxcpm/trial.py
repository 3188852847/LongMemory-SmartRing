"""独立 VoxCPM2 试听，不读取聊天、密钥或数据库，也不启动服务。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
REVISION = '32279effe8c19989596f05d353d1447f51d9e915'
MODEL = Path(r'D:\LongMemory-local\runtime\models\VoxCPM2') / REVISION
WEIGHTS = {'audiovae.pth': '94b5d51e107e0507d4acc976cfdadb64edd6fd06d1f751dadbf2fd1594274bf1',
           'model.safetensors': 'f7f964cfa9da23653baec6e6f7750719977ad944ed9f95fe52fe3a620506891d'}


def verify_weights():
    # 手动下载后也校验固定快照，避免半文件或错误版本进入模型加载。
    for name, expected in WEIGHTS.items():
        path = MODEL / name
        if not path.is_file():
            raise SystemExit('缺少模型文件：' + name)
        with path.open('rb') as handle:
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
        if actual != expected:
            raise SystemExit('模型文件校验失败：' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['download', 'verify', 'generate'])
    args = parser.parse_args()
    if args.action == 'download':
        from huggingface_hub import snapshot_download
        snapshot_download('openbmb/VoxCPM2', revision=REVISION, local_dir=str(MODEL),
                          token=False, max_workers=2)
        print('模型目录：', MODEL)
        return
    verify_weights()
    if args.action == 'verify':
        print('两个模型权重 SHA256 与官方固定版本一致。')
        return
    # 推理阶段禁止 HF 自动联网，不下载去噪/识别等额外模型。
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    import numpy as np
    import torch
    import soundfile as sf
    from voxcpm import VoxCPM
    if not torch.cuda.is_available():
        raise SystemExit('CUDA 不可用，停止而不是悄悄改用 CPU。')
    # PyPI 2.0.3 的 generate 尚不接受官方 main 分支文档里的 seed 参数；
    # 固定 PyTorch 随机源用于尽量减少试听波动，但不宣称跨平台完全确定。
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    started = time.perf_counter()
    model = VoxCPM.from_pretrained(str(MODEL), load_denoiser=False, optimize=False, device='cuda')
    load_seconds = time.perf_counter() - started
    output = ROOT / 'data/audio' / ('voxcpm-' + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    samples = [('plain', '你好，很高兴见到你。今天过得怎么样？我们慢慢聊。'),
               ('gentle', '(年轻女性，声音温柔明亮，语气自然，带着微笑)你好，很高兴见到你。今天过得怎么样？我们慢慢聊。')]
    records = []
    for name, text in samples:
        started = time.perf_counter()
        wav = model.generate(text=text, cfg_value=2.0, inference_timesteps=10,
                             normalize=False, denoise=False, retry_badcase=False, max_len=300)
        elapsed = time.perf_counter() - started
        if not len(wav) or not np.isfinite(wav).all():
            raise RuntimeError('无有效音频')
        rate = model.tts_model.sample_rate
        sf.write(str(output / (name + '.wav')), wav, rate)
        records.append({'name':name, 'text':text, 'generation_seconds':elapsed,
                        'audio_seconds':len(wav)/rate, 'sample_rate':rate})
    report = {'revision':REVISION, 'load_seconds':load_seconds, 'torch':torch.__version__,
              'gpu':torch.cuda.get_device_name(), 'peak_allocated_bytes':torch.cuda.max_memory_allocated(),
              'samples':records, 'randomness':'torch manual seed 42；PyPI 2.0.3 API 无 seed 参数，不保证完全确定',
              'note':'单次独立试听，不代表流式延迟或圆屏端到端性能。'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('试听目录：', output)


if __name__ == '__main__':
    main()
