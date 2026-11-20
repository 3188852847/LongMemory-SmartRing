"""用已核验的 assets 分区副本离线生成大肥鱼候选镜像；不访问设备。"""

import argparse
from pathlib import Path
import struct

from repack_assets import CAPACITY, ENTRY, parse


def build(original, figures):
    entries, _, end = parse(original, True)
    if len(original) != CAPACITY:
        raise ValueError("需要完整的 assets 分区")
    output = bytearray(original)
    base = 12 + len(entries) * ENTRY.size
    faces = {"thinking": "thinking", "sleepy": "sleep", "winking": "wink",
             "happy": "happy", "laughing": "happy", "loving": "happy"}
    changed = {}
    for index, (name, size, offset, width, height, _) in enumerate(entries):
        if not name.startswith("otto_") or not name.endswith(".gif"):
            continue
        emotion = name[5:-4]
        data = (figures / (faces.get(emotion, "neutral") + ".gif")).read_bytes()
        if (len(data) > size or data[:6] != b"GIF89a" or
                struct.unpack_from("<HH", data, 6) != (width, height) or (width, height) != (240, 240)):
            raise ValueError(f"资源与原槽尺寸或容量不符：{name}")
        start = base + offset + 2
        output[start:start + len(data)] = data
        struct.pack_into("<I", output, 12 + index * ENTRY.size + 32, len(data))
        changed[name] = data
    if len(changed) != 21:
        raise ValueError("未识别完整的 Otto 资源表")
    struct.pack_into("<I", output, 4, sum(output[12:end]) & 65535)
    verified, _, _ = parse(output, True)
    for before, after in zip(entries, verified, strict=True):
        if after[0] != before[0] or after[2:5] != before[2:5] or after[5] != changed.get(before[0], before[5]):
            raise ValueError("资源回读校验失败")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("original_partition", "figures", "output"):
        parser.add_argument(argument, type=Path)
    args = parser.parse_args()
    image = build(args.original_partition.read_bytes(), args.figures)
    with args.output.open("xb") as stream:
        stream.write(image)
