"""显式下载官方固定 BGE 快照；只下载所需文件，不执行仓库代码、不自动重试。"""

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

from longmemory.adapters.llm.local_embedding import MODEL_FILES, MODEL_ID, REVISION

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description="下载固定 BGE 快照，或校验导入手动下载的缺失文件")
    parser.add_argument("--from-directory", type=Path,
                        help="只从此目录读取缺失文件；仍查询官方元数据校验，但不请求文件下载")
    args = parser.parse_args(argv)
    target = ROOT / "data/models/bge-small-zh-v1.5" / REVISION
    # 允许显式再次运行以补齐缺失文件；既有文件必须重新通过官方哈希
    # 校验，绝不覆盖损坏内容，也不在一次运行里自动重试网络请求。
    if (target / "snapshot.json").exists():
        raise ValueError("完整快照记录已存在，未覆盖。")
    url = f"https://huggingface.co/api/models/{MODEL_ID}/revision/{REVISION}?blobs=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        metadata = json.load(response)
    if metadata["sha"] != REVISION:
        raise ValueError("官方返回的版本不匹配。")
    siblings = {item["rfilename"]: item for item in metadata["siblings"]}
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in (*MODEL_FILES, "README.md"):
        # README 包含上游许可及模型说明，下载但不作为推理配置加载。
        info = siblings[name]
        path = target / name
        if path.is_symlink():
            raise ValueError("不允许符号链接模型文件。")
        if path.exists():
            data = path.read_bytes()
        elif args.from_directory is not None:
            data = (args.from_directory / name).read_bytes()
        else:
            with urllib.request.urlopen(f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}", timeout=30) as response:
                data = response.read()
        if "lfs" in info:
            valid = hashlib.sha256(data).hexdigest() == info["lfs"]["sha256"]
        else:
            valid = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == info["blobId"]
        if not valid:
            raise ValueError("下载文件与官方内容哈希不一致。")
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
        if name in MODEL_FILES:
            hashes[name] = hashlib.sha256(data).hexdigest()
        print(f"已校验：{name} ({len(data)} bytes)", flush=True)
    with (target / "snapshot.json").open("x", encoding="utf-8") as stream:
        json.dump({"model": MODEL_ID, "revision": REVISION, "files": hashes}, stream, indent=2)
    print(f"模型目录：{target}")


if __name__ == "__main__":
    main()
