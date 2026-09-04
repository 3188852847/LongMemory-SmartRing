"""合成 YAML 同步验证，不读取或写入真实小智目录。"""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')
spec = importlib.util.spec_from_file_location('sync_role_test', Path(__file__).resolve().parents[3] / 'scripts/development/xiaozhi/sync_role.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


@pytest.fixture
def target(tmp_path):
    server = tmp_path / 'server'; (server / 'data').mkdir(parents=True)
    database = tmp_path / 'synthetic.db'
    config = {'selected_module': {'Memory': 'LongMemory'}, 'Memory': {'LongMemory': {'database_path': str(database), 'project_root': str(tmp_path)}},
              'LLM': {'api_key': 'SYNTHETIC_SECRET'}, 'prompt': '原角色', 'TTS': {'voice':'synthetic'}}
    path = server / 'data/.config.yaml'
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding='utf-8')
    return server, path, {'prompt':'新角色\n<memory></memory>', 'database':str(database), 'project':str(tmp_path), 'action':'check'}


def test_check_is_read_only_and_apply_preserves_config_and_backup(target):
    server, path, body = target; original = path.read_bytes()
    checked = module.sync(server, body)
    assert not checked['config_matches'] and path.read_bytes() == original
    assert len(list(path.parent.iterdir())) == 1
    result = module.sync(server, body | {'action':'apply', 'expected_digest':checked['digest']})
    assert result['config_matches'] and result['runtime'] == 'unverified'
    assert (path.parent / result['backup']).read_bytes() == original
    expected = yaml.safe_load(original); expected['prompt'] = body['prompt']
    assert yaml.safe_load(path.read_text(encoding='utf-8')) == expected
    assert 'SYNTHETIC_SECRET' not in json.dumps(result)
    assert module.sync(server, body)['config_matches']


def test_stale_digest_rejected_without_backup(target):
    server, path, body = target; original = path.read_bytes()
    with pytest.raises(ValueError):
        module.sync(server, body | {'action':'apply', 'expected_digest':'0'*64})
    assert path.read_bytes() == original and len(list(path.parent.iterdir())) == 1


@pytest.mark.parametrize('fragment', ['prompt: one\nprompt: two\n', 'prompt: &role one\nextra: *role\n', 'prompt: [one, two]\n', 'read_config_from_api: true\nprompt: one\n'])
def test_ambiguous_or_remote_config_rejected(target, fragment):
    server, path, body = target
    config = yaml.safe_load(path.read_text(encoding='utf-8')); del config['prompt']
    path.write_text(yaml.safe_dump(config) + fragment, encoding='utf-8')
    original = path.read_bytes()
    with pytest.raises(ValueError): module.sync(server, body)
    assert path.read_bytes() == original


@pytest.mark.parametrize('fragment', ['prompt: |\n  原角色\n  第二行\n# 后面注释\n', 'prompt: "原角色" # 注释\n', "prompt: '原角色'\n"])
def test_scalar_styles_and_comments_preserved(target, fragment):
    server, path, body = target
    config = yaml.safe_load(path.read_text(encoding='utf-8')); del config['prompt']
    text = yaml.safe_dump(config) + fragment + 'tail: unchanged\n'
    path.write_bytes(text.encode('utf-8'))
    original, updated, _ = module.prepare(path, body['prompt'], body['database'], body['project'])
    assert original == text.encode('utf-8')
    assert updated.endswith(b'tail: unchanged\n')
    assert yaml.safe_load(updated)['prompt'] == body['prompt']


def test_wrong_memory_database_rejected(target):
    server, path, body = target
    with pytest.raises(ValueError): module.sync(server, body | {'database':str(path.parent / 'wrong.db')})


def test_stdin_cli_never_prints_config(target):
    server, path, body = target
    result = subprocess.run([sys.executable, spec.origin, str(server)], input=json.dumps(body).encode(), capture_output=True, timeout=5)
    assert result.returncode == 0 and 'digest' in json.loads(result.stdout)
    assert b'SYNTHETIC_SECRET' not in result.stdout + result.stderr
