"""显式网络配置同步：不访问模型，只修改 server 下的三个地址字段。"""
import copy
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xiaozhi"))
from config_paths import config_path, backup_path


def updated_text(text, address):
    import yaml
    from network import private_ipv4
    address = private_ipv4(address)
    before = yaml.safe_load(text)
    expected = copy.deepcopy(before)
    values = {'ip': address, 'websocket': f'ws://{address}:8000/xiaozhi/v1/',
              'vision_explain': f'http://{address}:8003/mcp/vision/explain'}
    expected['server'].update(values)
    # 不重新序列化整份私有 YAML，避免改动人格、多行提示词或密钥格式。
    match = re.search(r'^server:[ \t]*(?:#.*)?\r?\n(?:(?:[ \t]+[^\n]*|[ \t]*|#[^\n]*)\r?\n)*', text, re.M)
    if not match:
        raise ValueError('Unsupported server block')
    block = match.group()
    for key, value in values.items():
        block, count = re.subn(rf'^(  {key}:)[^\r\n]*', lambda m: m[1] + ' ' + json.dumps(value), block, flags=re.M)
        if count != 1:
            raise ValueError('Ambiguous network field')
    result = text[:match.start()] + block + text[match.end():]
    if yaml.safe_load(result) != expected:
        raise ValueError('Unexpected configuration change')
    return result, str(before['server']['ip'])


def sync(path, address, apply=False):
    original = path.read_bytes()
    result, old = updated_text(original.decode('utf-8'), address)
    changed = result.encode('utf-8') != original
    if apply and changed:
        # 备份含原有凭据，只留在原私有目录，不复制到项目或输出正文。
        backup = backup_path(path, path.name + '.' + uuid.uuid4().hex + '.bak')
        with backup.open('xb') as handle:
            handle.write(original)
        if path.read_bytes() != original:
            raise ValueError('Configuration changed concurrently')
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        with temporary.open('xb') as handle:
            handle.write(result.encode('utf-8'))
        temporary.replace(path)
    return {'old_ip': old, 'new_ip': address, 'changed': changed}


if __name__ == '__main__':
    try:
        print(json.dumps(sync(config_path(Path(sys.argv[1])), sys.argv[2], sys.argv[3] == 'apply')))
    except Exception:
        raise SystemExit(3)
