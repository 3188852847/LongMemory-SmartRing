"""构建产物与分区容量检查；读取二进制文件，不访问串口或烧录设备。"""

import argparse
import hashlib
import json
from pathlib import Path
import struct

REQUIRED = ("xiaozhi.bin", "xiaozhi.elf", "xiaozhi.map", "bootloader/bootloader.bin",
            "partition_table/partition-table.bin", "generated_assets.bin")


def parse_partitions(data: bytes) -> dict:
    """读取实际编译分区表，避免把 CSV 空白自动偏移当成零或沿用错误的表。"""
    partitions = {}
    verified = False
    for offset in range(0, len(data), 32):
        chunk = data[offset:offset + 32]
        if len(chunk) != 32:
            raise ValueError("分区表长度无效。")
        magic = struct.unpack_from("<H", chunk)[0]
        if magic == 0xEBEB:
            if hashlib.md5(data[:offset]).digest() != chunk[16:32]:
                raise ValueError("分区表 MD5 不一致。")
            if any(byte != 0xFF for byte in data[offset + 32:]):
                raise ValueError("分区表校验尾部存在额外内容。")
            verified = True
            break
        if magic != 0x50AA:
            raise ValueError("分区表记录无效或缺少校验。")
        _, kind, subtype, start, size, label, flags = struct.unpack("<HBBII16sI", chunk)
        name = label.rstrip(b"\x00").decode("ascii")
        if not name or name in partitions or not size or start + size > 16 * 1024 * 1024:
            raise ValueError("分区命名或 16 MB 范围无效。")
        partitions[name] = {"type": "app" if kind == 0 else kind, "subtype": subtype,
                            "offset": start, "size": size, "flags": flags}
    if not partitions or not verified:
        raise ValueError("分区表为空或缺少校验。")
    ordered = sorted(partitions.values(), key=lambda item: item["offset"])
    if any(a["offset"] + a["size"] > b["offset"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("分区范围重叠。")
    return partitions


def check(build: Path) -> dict:
    description = json.loads((build / "project_description.json").read_text(encoding="utf-8"))
    if description.get("target") != "esp32s3" or description.get("project_name") != "xiaozhi":
        raise ValueError("产物不是预期的圆屏工程或 ESP32-S3 目标。")
    partitions = parse_partitions((build / "partition_table/partition-table.bin").read_bytes())
    apps = [value for value in partitions.values() if value["type"] == "app"]
    if not apps:
        raise ValueError("分区表没有应用分区。")
    artifacts = {}
    for name in REQUIRED:
        data = (build / name).read_bytes()
        if not data:
            raise ValueError(f"产物为空：{name}")
        artifacts[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if not (build / "xiaozhi.elf").read_bytes().startswith(b"\x7fELF"):
        raise ValueError("ELF 产物格式无效。")
    for name in ("xiaozhi.bin", "bootloader/bootloader.bin"):
        data = (build / name).read_bytes()
        if len(data) < 24 or data[0] != 0xE9 or struct.unpack_from("<H", data, 12)[0] != 9:
            raise ValueError("镜像不是 ESP32-S3 格式。")
    app_size = artifacts["xiaozhi.bin"]["bytes"]
    if app_size > min(partition["size"] for partition in apps):
        raise ValueError("应用镜像超过应用分区容量。")
    assets = partitions.get("assets")
    if not assets or artifacts["generated_assets.bin"]["bytes"] > assets["size"]:
        raise ValueError("基础显示资源镜像超过 assets 分区容量。")
    result = {"schema_version": 1, "target": "esp32s3", "project_version": description.get("project_version"),
              "artifacts": artifacts, "partitions": partitions,
              "application_remaining_bytes": min(partition["size"] for partition in apps) - app_size,
              "base_assets_remaining_bytes": assets["size"] - artifacts["generated_assets.bin"]["bytes"],
              "compiled": True, "flashed": False}
    (build / "restore-build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.build)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"产物检查失败：{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
