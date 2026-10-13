"""由所有者显式执行的语音资源下载入口；运行服务时不调用本工具。

清单固定官方 URL、长度与摘要。旧备份只提供版本依据，不参与资源部署。
每个下载先写 .part，完整校验后才发布；失败不重试，不覆盖损坏的已发布文件。
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[3]
LOCAL = ROOT / "local"
MANIFEST = Path(__file__).with_name("assets.json")
OPUS_SHA256 = "995e23c399522546397f9059f10365702dec3ceadbaf34b8ecd4c5e977822603"


def local_path(relative, local=LOCAL):
    """清单和压缩包中的路径只能落在项目专属资源根内部。"""
    root = local.resolve()
    target = (root / relative).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("资源路径超出 local 目录")
    return target


def validate(path, asset):
    if path.stat().st_size != asset["size"]:
        raise ValueError(f"资源长度不一致：{asset['name']}")
    digest = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(asset["size"]).encode() + b"\0")
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            blob.update(block)
    if asset.get("sha256") and digest.hexdigest() != asset["sha256"]:
        raise ValueError(f"SHA-256 不一致：{asset['name']}")
    # LFS 的 blobId 指向 Git 中的指针文件，权重本体必须用 LFS SHA-256 校验。
    if not asset.get("sha256") and asset.get("git_blob") and blob.hexdigest() != asset["git_blob"]:
        raise ValueError(f"Git 文件摘要不一致：{asset['name']}")
    if not asset.get("sha256") and not asset.get("git_blob"):
        raise ValueError("资源清单缺少摘要")
    return digest.hexdigest()


def download(asset, local=LOCAL):
    path = local_path(asset["target"], local)
    if path.exists():
        digest = validate(path, asset)
        print(f"已校验：{asset['name']}", flush=True)
        return digest
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > asset["size"]:
        raise ValueError("未完成文件超过清单长度；保留文件，请先检查")
    if offset < asset["size"]:
        headers = {"User-Agent": "SmartRoundScreen-VoiceRestore/1", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(asset["url"], headers=headers)
        print(f"下载：{asset['name']}（{offset}/{asset['size']} 字节）", flush=True)
        with urllib.request.urlopen(request, timeout=90) as response:
            if offset:
                expected = f"bytes {offset}-{asset['size'] - 1}/{asset['size']}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise ValueError("服务器未接受断点续传；保留原 .part，请反馈此错误")
            elif response.status != 200:
                raise ValueError("下载响应无效")
            written, next_progress = offset, offset + 64 * 1024 * 1024
            with partial.open("ab" if partial.exists() else "xb") as output:
                while block := response.read(1024 * 1024):
                    if written + len(block) > asset["size"]:
                        raise ValueError("下载超出固定资源长度")
                    output.write(block)
                    written += len(block)
                    if written >= next_progress:
                        print(f"  {asset['name']}：{written * 100 // asset['size']}%", flush=True)
                        next_progress = written + 64 * 1024 * 1024
    digest = validate(partial, asset)
    # 目标此前不存在；不用 replace，避免覆盖并发写入的文件。
    partial.rename(path)
    return digest


def publish_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest():
            raise ValueError("已有工具文件与新下载资源不一致；未覆盖")
        return
    with path.open("xb") as output:
        output.write(content)


def unpack_tools(local=LOCAL):
    """只部署新下载包中的工具；不修改 PATH，不启动安装器或联网服务。"""
    archive = local_path("downloads/ffmpeg-9.0.1-essentials_build.zip", local)
    prefix = "ffmpeg-9.0.1-essentials_build/"
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if member.is_dir():
                continue
            if not member.filename.startswith(prefix):
                raise ValueError("FFmpeg ZIP 根目录与固定版本不一致")
            relative = member.filename[len(prefix):]
            if "\\" in relative or ".." in Path(relative).parts:
                raise ValueError("压缩包路径不合法")
            target = local_path("tools/ffmpeg/" + relative, local)
            publish_bytes(target, package.read(member))
    seven_zip = shutil.which("7z")
    if not seven_zip:
        raise ValueError("未找到机器已登记的 7z 命令；请检查稳定工具入口")
    archive = local_path("downloads/libopus-1.6.1-h6a83c73_0.conda", local)
    name = "pkg-libopus-1.6.1-h6a83c73_0.tar.zst"
    with zipfile.ZipFile(archive) as package:
        compressed = package.read(name)
    compressed_path = local_path("downloads/" + name, local)
    publish_bytes(compressed_path, compressed)
    result = subprocess.run([seven_zip, "x", str(compressed_path), "-so"], capture_output=True)
    if result.returncode:
        raise ValueError("7-Zip 解码 Opus 包失败；未输出第三方日志")
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as package:
        member = package.getmember("Library/bin/opus.dll")
        if not member.isfile():
            raise ValueError("Opus 包内容无效")
        content = package.extractfile(member).read()
    if hashlib.sha256(content).hexdigest() != OPUS_SHA256:
        raise ValueError("Opus DLL 与原已验证版本不一致")
    target = local_path("runtime/xiaozhi-esp32-server/main/xiaozhi-server/native/libopus-1.6.1/Library/bin/opus.dll", local)
    publish_bytes(target, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", required=True, choices=("models", "tools"))
    parser.add_argument("--check-only", action="store_true")
    arguments = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = {}
    for asset in manifest["assets"]:
        if asset["group"] != arguments.group:
            continue
        results[asset["target"]] = (
            validate(local_path(asset["target"]), asset)
            if arguments.check_only else download(asset)
        )
    if arguments.group == "tools" and not arguments.check_only:
        unpack_tools()
    if not arguments.check_only:
        receipt = LOCAL / "downloads" / f"voice-{arguments.group}-receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{arguments.group}：{len(results)} 个资源全部校验通过；仍需运行验收。", flush=True)


if __name__ == "__main__":
    main()
