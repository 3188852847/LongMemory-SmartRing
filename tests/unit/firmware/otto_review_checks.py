"""Independent synthetic assets checks; no device image or private data input."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--implementation', type=Path, required=True)
    parser.add_argument('--public-assets', type=Path, required=True)
    parser.add_argument('--native-source', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    output = repo / 'data/test-tmp' / f'otto-review-{os.getpid()}-{uuid.uuid4().hex}'
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('reviewed_repack', args.implementation)
    implementation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(implementation)
    assert Path(implementation.__file__).resolve() == args.implementation.resolve()
    original_index = args.public_assets.read_bytes()
    before, original_payload, old_used = implementation.parse(original_index)
    assert len(before) == 23 and old_used == 352105
    # 固定来源的大小仅用于边界验证；合成 GIF 不作为视觉/解码验收素材。
    sizes = [35131,80122,107068,99502,96092,90728,39075,97836,39521,84972,
             78215,78147,26011,72635,32503,126729,105610,91193,48890,84984,94495]
    files = []
    for index, size in enumerate(sizes):
        name = f'face{index}.gif'
        data = b'GIF89a' + struct.pack('<HH', 240, 240) + bytes([index + 1]) * (size - 10)
        (output / name).write_bytes(data)
        blob = hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + data).hexdigest()
        files.append({'path': name, 'bytes': size, 'git_blob_sha1': blob})
    manifest = output / 'synthetic-manifest.json'
    manifest.write_text(json.dumps({'commit': '970cf66906d7c30059faa2704e7002f06b8c3619',
                                    'files': files}), encoding='utf-8')
    original = original_index + b'\x12' * (implementation.CAPACITY - len(original_index))
    review = {'original_image_sha256': implementation.sha(original), 'original_used_bytes': old_used,
              'no_reachable_tail_consumers': True, 'code_evidence': ['synthetic fixture only']}
    image, receipt = implementation.repack(original, output, manifest, review)
    final = image + original[len(image):]
    after, payload, used = implementation.parse(final, True)
    assert before == after[:23]
    assert payload[:len(original_payload)] == original_payload
    assert used == 1962530 and len(image) == 1966080
    assert len(image) - used == 3550
    assert final[used:] == original[used:]
    assert len(after) == 44
    # 表从23项扩为44项：原offset不变，物理资源地址统一增加924字节。
    assert (44 - 23) * implementation.ENTRY.size == 924
    for case, mutated_review in [('no_review', None), ('wrong_hash', dict(review, original_image_sha256='bad'))]:
        try:
            implementation.repack(original, output, manifest, mutated_review)
        except ValueError:
            pass
        else:
            raise AssertionError(case + ' must reject')
    paths = ['main/application.cc', 'main/display/display.h',
             'main/display/lvgl_display/gif/lvgl_gif.cc', 'main/display/lvgl_display/gif/lvgl_gif.h',
             'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc',
             'main/boards/viewe-smartring-plus/otto_state.h']
    fingerprints = {path: hashlib.sha256((args.native_source/path).read_text(encoding='utf-8').encode()).hexdigest()
                    for path in paths}
    result = {'implementation': str(args.implementation.resolve()), 'public_assets': str(args.public_assets),
              'checks': ['23 resources and payload preserved', '44 entries and relocated addresses',
                         'exact minimal write/last sector/remainder', 'unreviewed tail rejected',
                         'wrong original fingerprint rejected'],
              'used_bytes': used, 'write_bytes': len(image), 'source_normalized_sha256': fingerprints}
    (output/'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    print('Local synthetic evidence: ' + str(output/'result.json'))


if __name__ == '__main__':
    main()
