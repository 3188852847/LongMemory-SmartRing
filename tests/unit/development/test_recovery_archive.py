"""重装包使用合成数据验证去重、损坏检测与禁止覆盖，不访问个人数据。"""

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


spec = importlib.util.spec_from_file_location(
    'recovery_archive', Path(__file__).resolve().parents[3] / 'scripts/development/recovery_archive.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def test_duplicate_content_restores_both_original_paths(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'synthetic media')
    bundle = tmp_path / 'backup.zip'
    result = archive.create(bundle, [(source, 'D/project/a'), (source, 'D/project/b')])
    assert result['files'] == 2
    assert result['unique_contents'] == 1
    archive.restore(bundle, tmp_path / 'restored')
    assert (tmp_path / 'restored/D/project/a').read_bytes() == source.read_bytes()
    assert (tmp_path / 'restored/D/project/b').read_bytes() == source.read_bytes()


def test_restore_rejects_existing_destination(tmp_path):
    target = tmp_path / 'existing'
    target.mkdir()
    (target / 'keep').write_text('keep')
    with pytest.raises(ValueError, match='禁止覆盖'):
        archive.restore(tmp_path / 'unused.zip', target)
    assert (target / 'keep').read_text() == 'keep'


@pytest.mark.parametrize('path', ['../escape', '/absolute', 'D:/escape', 'a\\b', 'a/../../b', 'D/con.txt'])
def test_unsafe_manifest_rejected_before_creating_destination(tmp_path, path):
    bundle = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bundle, 'w') as output:
        output.writestr('manifest.json', json.dumps({'format': 1, 'files': [
            {'path': path, 'size': 0, 'sha256': '0' * 64}]}))
    with pytest.raises(ValueError):
        archive.restore(bundle, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()


def test_tampered_content_is_rejected(tmp_path):
    bundle = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bundle, 'w') as output:
        output.writestr('manifest.json', json.dumps({'format': 1, 'files': [
            {'path': 'D/file', 'size': 3, 'sha256': '0' * 64}]}))
        output.writestr('blobs/' + '0' * 64, b'bad')
    with pytest.raises(ValueError, match='校验失败'):
        archive.verify(bundle)


def test_empty_bundle_and_existing_bundle_protection(tmp_path):
    bundle = tmp_path / 'empty.zip'
    assert archive.create(bundle, [])['files'] == 0
    with pytest.raises(FileExistsError):
        archive.create(bundle, [])


def test_windows_case_collision_rejected(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'x')
    with pytest.raises(ValueError, match='重复恢复路径'):
        archive.create(tmp_path / 'case.zip', [(source, 'D/A'), (source, 'D/a')])
