"""从项目私有 .env 同步学校模型配置到小智私有 YAML，不输出凭据。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from sync_role import commit_change


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def update(project: Path, server: Path) -> dict[str, str]:
    import yaml
    source = read_env(project / '.env')
    required = ('LONGMEMORY_LLM_BASE_URL', 'LONGMEMORY_LLM_MODEL', 'LONGMEMORY_LLM_API_KEY')
    if any(not source.get(key) for key in required):
        raise ValueError('missing_private_model_setting')
    base = source['LONGMEMORY_LLM_BASE_URL'].rstrip('/')
    if not base.endswith('/v1') or base.endswith('/chat/completions'):
        raise ValueError('invalid_base_url')
    path = server / 'data/.config.yaml'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('unsafe_config')
    original = path.read_bytes()
    text = original.decode('utf-8')
    config = yaml.safe_load(text)
    if (not isinstance(config, dict)
            or config.get('read_config_from_api', False)
            or config.get('selected_module', {}).get('LLM') != 'CampusLLM'):
        raise ValueError('unsupported_config')
    target = config.get('LLM', {}).get('CampusLLM')
    if not isinstance(target, dict) or target.get('type') != 'openai':
        raise ValueError('unsupported_provider')
    if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
        raise ValueError('unsupported_alias')
    node = yaml.compose(text)
    for key in ('LLM', 'CampusLLM'):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError('ambiguous_config')
        matches = [value for candidate, value in node.value if candidate.value == key]
        if len(matches) != 1:
            raise ValueError('ambiguous_config')
        node = matches[0]
    values = {'base_url': base, 'model_name': source['LONGMEMORY_LLM_MODEL'],
              'api_key': source['LONGMEMORY_LLM_API_KEY']}
    replacements = []
    for key, value in values.items():
        matches = [child for candidate, child in node.value if candidate.value == key]
        if len(matches) != 1 or not isinstance(matches[0], yaml.ScalarNode):
            raise ValueError('ambiguous_config')
        child = matches[0]
        replacements.append((child.start_mark.index, child.end_mark.index, json.dumps(value, ensure_ascii=False)))
    updated_text = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_text = updated_text[:start] + replacement + updated_text[end:]
    expected = copy.deepcopy(config)
    expected['LLM']['CampusLLM'].update(values)
    if yaml.safe_load(updated_text) != expected:
        raise ValueError('unexpected_config_change')
    return commit_change(path, {'action': 'apply', 'expected_digest': hashlib.sha256(original).hexdigest()},
                         original, updated_text.encode('utf-8'), False, backup_label='model')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--server', type=Path, required=True)
    try:
        args = parser.parse_args()
        result = update(args.project.resolve(), args.server.resolve())
        print('模型私有配置已更新；备份：' + result['backup'])
        print('配置摘要：' + result['digest'])
    except Exception:
        print('模型私有配置更新失败；未输出配置内容。')
        raise SystemExit(3)
