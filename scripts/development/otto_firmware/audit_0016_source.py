"""Freeze the isolated 0016 two-patch candidate, without SDK/source/device writes.

Hashes the complete previously copied source set, checks original 0015 retention,
then applies/reverses the patches in a new eight-file disposable fixture only.
"""
import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

CONSUMER = ('main/application.cc', 'main/application.h', 'main/audio/audio_service.cc',
            'main/audio/audio_service.h', 'main/protocols/protocol.h', 'main/protocols/websocket_protocol.cc')
BOARD = 'main/boards/viewe-smartring-plus/viewe-smartring-plus.cc'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(repo, baseline, source, checkpoint, evidence):
    repo, baseline, source, evidence = (p.resolve() for p in (repo, baseline, source, evidence))
    if evidence.exists():
        raise ValueError('new evidence directory required')
    before = json.loads(checkpoint.read_text(encoding='utf-8'))['before']
    original = {name: sha(baseline / name) for name in before}
    if original != before:
        raise ValueError('original 0015 differs from pre-copy checkpoint')
    after = {name: sha(source / name) for name in before}
    changed = sorted(name for name in before if before[name] != after[name])
    if changed != sorted((*CONSUMER, BOARD, 'CMakeLists.txt')):
        raise ValueError('unexpected source changes: ' + repr(changed))
    extras = sorted(str(p.relative_to(source)).replace('\\', '/') for p in source.rglob('*')
                    if p.is_file() and not p.name.endswith('.log') and str(p.relative_to(source)).replace('\\', '/') not in before)
    if extras:
        raise ValueError('unexpected source additions: ' + repr(extras))
    if any(p.is_symlink() or p.is_junction() for p in source.rglob('*')):
        raise ValueError('source must contain physical files only')
    consumer_patch = repo / 'firmware/smartring_plus/patches/0016-tts-interrupt-v1.patch'
    caption_patch = repo / 'firmware/smartring_plus/patches/0016-round-subtitle-safe-area.patch'
    diff = []
    for name in CONSUMER:
        for line in difflib.unified_diff((baseline / name).read_text(encoding='utf-8').splitlines(keepends=True),
                                        (source / name).read_text(encoding='utf-8').splitlines(keepends=True),
                                        fromfile='a/' + name, tofile='b/' + name):
            # 原始头文件有无末尾换行的差异，必须保留Git的精确标记。
            diff.append(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n')
    patch_bytes = ''.join(diff).encode('utf-8')
    if consumer_patch.exists():
        if consumer_patch.read_bytes() != patch_bytes:
            raise ValueError('refusing to overwrite different frozen patch')
    else:
        consumer_patch.write_bytes(patch_bytes)
    evidence.mkdir(parents=True)
    (evidence / 'source-hashes-before-patch-check.json').write_text(json.dumps({'before': before, 'after': after, 'changed': changed}, indent=2), encoding='utf-8')
    fixture = evidence / 'patch-roundtrip'
    for name in changed:
        (fixture / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline / name, fixture / name)
    directory = str(fixture.relative_to(repo)).replace('\\', '/')
    def apply(patch, reverse=False, check=False):
        command = ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'apply', '--whitespace=nowarn', '--directory=' + directory]
        if reverse:
            command.append('--reverse')
        if check:
            command.append('--check')
        result = subprocess.run(command + [str(patch)], cwd=repo, capture_output=True)
        with (evidence / 'patch-commands.log').open('ab') as log:
            log.write((' '.join(command + [str(patch)]) + '\n').encode())
            log.write(result.stdout + result.stderr)
        result.check_returncode()
    for patch in (caption_patch, consumer_patch):
        apply(patch, check=True)
        apply(patch)
    if any(sha(fixture / name) != after[name] for name in changed):
        raise ValueError('forward patch bytes do not match candidate')
    for patch in (consumer_patch, caption_patch):
        apply(patch, reverse=True, check=True)
        apply(patch, reverse=True)
    if any(sha(fixture / name) != before[name] for name in changed):
        raise ValueError('reverse patch bytes do not restore original')
    record = {'baseline': str(baseline), 'source': str(source), 'files': len(before), 'changed': changed,
              'before': before, 'after': after, 'original_0015_unchanged': True,
              'non_target_files_unchanged': len(before) - len(changed), 'forward_reverse_byte_verification': True,
              'patches': {str(p.relative_to(repo)).replace('\\', '/'): sha(p) for p in (caption_patch, consumer_patch)},
              'device_or_serial_actions': False}
    (evidence / 'source-audit.json').write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({key: record[key] for key in ['files', 'changed', 'original_0015_unchanged', 'non_target_files_unchanged', 'forward_reverse_byte_verification', 'patches']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('repo', 'baseline', 'source', 'checkpoint', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    audit(args.repo, args.baseline, args.source, args.checkpoint, args.evidence)
