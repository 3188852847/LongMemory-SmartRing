"""受控网络同步：不访问模型，只更新 server 下的地址、端口和对应 URL。"""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "xiaozhi"))
from config_paths import config_path, backup_path


def updated_text(text, address, ws_port=8000, http_port=8003):
    import yaml
    from network import private_ipv4
    from voice_ports import validate_voice_ports
    address = private_ipv4(address)
    validate_voice_ports(ws_port, http_port)
    before = yaml.safe_load(text)
    expected = copy.deepcopy(before)
    values = {'ip': address, 'websocket': f'ws://{address}:{ws_port}/xiaozhi/v1/',
              'vision_explain': f'http://{address}:{http_port}/mcp/vision/explain'}
    # 兼容旧精简配置；新端口要求两个字段均存在，退回默认也同步现有字段。
    for key, value in (('port', ws_port), ('http_port', http_port)):
        if key in before['server'] or (ws_port, http_port) != (8000, 8003):
            values[key] = value
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


def sync(path, address, apply=False, ws_port=8000, http_port=8003, expected_digest=None):
    original = path.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if expected_digest is not None and expected_digest != digest:
        raise ValueError('Configuration changed since network check')
    result, old = updated_text(original.decode('utf-8'), address, ws_port, http_port)
    changed = result.encode('utf-8') != original
    if apply and changed:
        # 备份含原有凭据，只留在原私有目录，不复制到项目或输出正文。
        backup = backup_path(path, path.name + '.' + uuid.uuid4().hex + '.bak')
        with backup.open('xb') as handle:
            handle.write(original)
        if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
            raise ValueError('Network backup verification failed')
        if path.read_bytes() != original:
            raise ValueError('Configuration changed concurrently')
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        with temporary.open('xb') as handle:
            handle.write(result.encode('utf-8'))
        temporary.replace(path)
    return {'old_ip': old, 'new_ip': address, 'changed': changed, 'digest': digest,
            'new_digest': hashlib.sha256(result.encode('utf-8')).hexdigest()}


def run_sync(server, address, apply=False, ws_port=8000, http_port=8003, expected_digest=None, refresh_consumer=False):
    path = config_path(server)
    checked = sync(path, address, False, ws_port, http_port, expected_digest)
    plan = None
    if refresh_consumer:
        from network_copy import plan_copy, backup_copy
        original = path.read_bytes()
        if hashlib.sha256(original).hexdigest() != checked['digest']:
            raise ValueError('Configuration changed during network planning')
        after = updated_text(original.decode('utf-8'), address, ws_port, http_port)[0].encode('utf-8')
        plan = plan_copy(server, original, after, updated_text)
        if apply:
            backup_copy(plan)
    if not apply:
        return checked
    result = sync(path, address, True, ws_port, http_port, checked['digest'])
    if refresh_consumer:
        from network_copy import write_copy
        write_copy(plan)
    return result


if __name__ == '__main__':
    try:
        ports = [int(value) for value in sys.argv[4:6]] or [8000, 8003]
        expected = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else None
        refresh = len(sys.argv) > 7 and sys.argv[7] == 'refresh-network-copy'
        print(json.dumps(run_sync(Path(sys.argv[1]), sys.argv[2], sys.argv[3] == 'apply', *ports, expected, refresh)))
    except Exception:
        raise SystemExit(3)
