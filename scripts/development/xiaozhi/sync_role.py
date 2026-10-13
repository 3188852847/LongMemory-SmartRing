"""由小智现有 Python 执行：只修改私有 YAML 的 prompt 标量。

输入走 stdin，不把提示词放在进程参数；输出仅状态，绝不输出私有 YAML。
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from config_paths import config_path, backup_path
import sys
import uuid


def prepare(path, prompt, database, project):
    import yaml
    if path.is_symlink() or path.resolve().parent != path.parent.resolve():
        raise ValueError('unsafe_target')
    original = path.read_bytes()
    if len(original) > 1024 * 1024:
        raise ValueError('oversized_config')
    text = original.decode('utf-8')
    before = yaml.safe_load(text)
    if not isinstance(before, dict) or before.get('read_config_from_api', False):
        raise ValueError('unsupported_config')
    memory = before.get('Memory', {}).get('LongMemory', {})
    # 角色和声音属于独立配置域。这里只用保留的 LongMemory 配置块确认
    # “这是本项目的那份小智 YAML”，不能要求它恰好是当前启用的记忆后端。
    if (Path(memory.get('database_path', '')).resolve() != Path(database).resolve() or
            Path(memory.get('project_root', '')).resolve() != Path(project).resolve()):
        raise ValueError('memory_config_mismatch')
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError('unsupported_alias')
    tree = yaml.compose(text)
    keys = [key.value for key, _ in tree.value]
    if len(keys) != len(set(keys)) or keys.count('prompt') != 1:
        raise ValueError('ambiguous_config')
    node = next(value for key, value in tree.value if key.value == 'prompt')
    if not isinstance(node, yaml.ScalarNode) or not isinstance(before['prompt'], str):
        raise ValueError('unsupported_prompt')
    # JSON 引号字符串也是合法 YAML。仅替换标量区间，其他字段原字节保留。
    previous = text[node.start_mark.index:node.end_mark.index]
    replacement = json.dumps(prompt, ensure_ascii=False)
    if previous.endswith('\n'):
        replacement += '\r\n' if previous.endswith('\r\n') else '\n'
    updated = text[:node.start_mark.index] + replacement + text[node.end_mark.index:]
    expected = copy.deepcopy(before); expected['prompt'] = prompt
    if yaml.safe_load(updated) != expected:
        raise ValueError('unexpected_config_change')
    return original, updated.encode('utf-8'), before['prompt'] == prompt


def sync(server, body):
    path = config_path(server)
    if body.get('action') not in {'check', 'apply'} or not isinstance(body.get('prompt'), str) or not 1 <= len(body['prompt']) <= 16000:
        raise ValueError('invalid_request')
    original, updated, matches = prepare(path, body['prompt'], body['database'], body['project'])
    return commit_change(path, body, original, updated, matches)


def commit_change(path, body, original, updated, matches, backup_label='role'):
    """角色和音色共用排他锁、原文备份与版本检查，不覆盖并发修改。"""
    digest = hashlib.sha256(original).hexdigest()
    result = {'config_matches': matches, 'digest': digest, 'runtime': 'unverified'}
    if body['action'] == 'check':
        return result
    if body.get('expected_digest') != digest:
        raise ValueError('config_changed')
    if matches:
        return result
    # 同步调用间使用原目录排他锁；其他编辑器仍需避免同时编辑该配置。
    lock_path = path.with_name('.longmemory-role-sync.lock')
    with lock_path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if path.read_bytes() != original:
                raise ValueError('config_changed')
            if backup_label not in {'role', 'model', 'tts', 'memory', 'vad'}:
                raise ValueError('invalid_backup_label')
            backup = backup_path(path, path.name + '.' + backup_label + '-' + uuid.uuid4().hex + '.bak')
            with backup.open('xb') as handle:
                handle.write(original)
                handle.flush(); os.fsync(handle.fileno())
            temporary = path.with_name(path.name + '.' + backup_label + '-' + uuid.uuid4().hex + '.tmp')
            with temporary.open('xb') as handle:
                handle.write(updated)
                handle.flush(); os.fsync(handle.fileno())
            if path.read_bytes() != original:
                raise ValueError('config_changed')
            temporary.replace(path)
            # 回读只证明磁盘文件，不证明运行中的小智已加载。
            if path.read_bytes() != updated:
                raise ValueError('write_unverified')
            return {'config_matches': True, 'digest': hashlib.sha256(updated).hexdigest(),
                    'runtime': 'unverified', 'backup': backup.name}
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == '__main__':
    try:
        data = json.loads(sys.stdin.buffer.read(90000))
        result = sync(Path(sys.argv[1]).resolve(), data)
        print(json.dumps(result))
    except Exception:
        # 不透传带密钥或完整输入的第三方异常。
        print('{"error":"device_role_sync_failed"}')
        raise SystemExit(3)
