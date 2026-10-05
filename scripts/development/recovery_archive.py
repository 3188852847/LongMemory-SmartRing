"""重装备份的去重打包、完整性校验和隔离展开；不覆盖现有项目。

包内按 SHA-256 保存一份内容，manifest 保存每个原始路径的映射。
这样两份相同原视频可以只存一次，恢复时仍生成原来的两个文件。
只使用标准库，重装后安装 Python 即可读取，不依赖项目环境。
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def safe_path(value):
    """只接受包内相对路径，也拒绝 Windows 盘符、设备名和路径穿越。"""
    if not isinstance(value, str) or '\\' in value or ':' in value:
        raise ValueError('非法恢复路径')
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or str(path) != value:
        raise ValueError('非法恢复路径')
    for part in path.parts:
        if part in {'.', '..'} or part.endswith((' ', '.')) or any(ord(c) < 32 for c in part):
            raise ValueError('非法恢复路径')
        if re.fullmatch(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])', part.split('.')[0]):
            raise ValueError('Windows 保留路径')
    return path


def create(archive, files, metadata=None):
    """files 为 (读取文件, 恢复相对路径)；调用方负责目录筛选和 SQLite 一致性快照。"""
    records, seen_paths, blobs = [], set(), set()
    archive = Path(archive)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
        for source, target in files:
            safe_path(target)
            key = target.casefold()
            if key in seen_paths:
                raise ValueError(f'重复恢复路径: {target}')
            seen_paths.add(key)
            source = Path(source)
            before = source.stat()
            sha = digest(source)
            member = f'blobs/{sha}'
            if sha not in blobs:
                bundle.write(source, member)
                blobs.add(sha)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f'备份期间源文件变化: {target}')
            records.append({'path': target, 'sha256': sha, 'size': before.st_size})
        bundle.writestr('manifest.json', json.dumps(
            {'format': 1, 'metadata': metadata or {}, 'files': records}, ensure_ascii=False, indent=2))
    # 从压缩包重新读取全部内容验证，不能以成功写出文件替代完整性检查。
    return verify(archive)


def verify(archive):
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise ValueError('重复 ZIP 条目')
        manifest = json.loads(bundle.read('manifest.json'))
        if manifest.get('format') != 1:
            raise ValueError('不支持的备份格式')
        checked, paths = {}, set()
        for item in manifest['files']:
            safe_path(item['path'])
            key = item['path'].casefold()
            if key in paths:
                raise ValueError('重复恢复路径')
            paths.add(key)
            sha = item['sha256']
            if not re.fullmatch('[0-9a-f]{64}', sha):
                raise ValueError('非法内容摘要')
            if sha not in checked:
                result, size = hashlib.sha256(), 0
                with bundle.open(f'blobs/{sha}') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        size += len(chunk)
                        result.update(chunk)
                if result.hexdigest() != sha:
                    raise ValueError('文件内容校验失败')
                checked[sha] = size
            if checked[sha] != item['size']:
                raise ValueError('文件长度校验失败')
        if set(names) != {'manifest.json', *(f'blobs/{sha}' for sha in checked)}:
            raise ValueError('发现清单之外的 ZIP 内容')
    return {'files': len(paths), 'unique_contents': len(checked),
            'restored_bytes': sum(f['size'] for f in manifest['files']),
            'archive_bytes': Path(archive).stat().st_size, 'sha256': digest(archive)}


def restore(archive, destination):
    """仅展开到一个尚不存在的新目录；绝不按清单直接覆盖 C/D 盘。"""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('恢复目录必须尚不存在，禁止覆盖现有文件')
    result = verify(archive)
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    display_root = str(root)
    if os.name == 'nt' and not str(root).startswith('\\\\?\\'):
        # 厂家源码本身就接近 MAX_PATH；隔离恢复再加一层目录会超过 260 字符。
        # 使用 Windows 扩展路径访问文件，不改系统注册表，也不缩短或丢弃文件名。
        value = str(root)
        root = Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        for item in manifest['files']:
            target = root.joinpath(*safe_path(item['path']).parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError('恢复路径越界')
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(f"blobs/{item['sha256']}") as source, target.open('xb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if digest(target) != item['sha256']:
                raise ValueError('展开后的文件校验失败')
    return result | {'restored_to': display_root}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['verify', 'restore'])
    parser.add_argument('archive', type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.operation == 'restore':
        if args.destination is None:
            parser.error('restore 需要 --destination，且该目录必须尚不存在')
        result = restore(args.archive, args.destination)
    else:
        result = verify(args.archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
