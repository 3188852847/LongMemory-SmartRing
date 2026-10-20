"""停止态网络副本投影：保留已验证Hy网关和全部非网络字段。"""

import json
from pathlib import Path
from uuid import uuid4

from config_paths import managed_project, config_path, _safe, _digest, _atomic


def plan_copy(server, before, after, rewrite):
    project = managed_project(server)
    if project is None:
        return None
    source = config_path(server)
    target = Path(server) / 'data/.config.yaml'
    marker = target.with_name('.config.source.json')
    for path in (source, target, marker):
        _safe(path, project)
    if not target.is_file() or not marker.is_file() or target.stat().st_size > 1024 * 1024 or marker.stat().st_size > 8192:
        raise ValueError('network_copy_ownership_unconfirmed')
    old = target.read_bytes()
    old_marker = marker.read_bytes()
    body = json.loads(old_marker.decode('utf-8'))
    if body.get('source') != 'local/config/xiaozhi.yaml' or body.get('sha256') != _digest(old):
        raise ValueError('network_copy_changed')
    projection = body.get('model_projection')
    if projection == 'owned_hy_gateway':
        if body.get('canonical_sha256') != _digest(before):
            raise ValueError('network_copy_canonical_changed')
    elif projection is not None or old != before:
        raise ValueError('network_copy_projection_unconfirmed')
    import yaml
    network = yaml.safe_load(after)['server']
    content = rewrite(old.decode('utf-8'), network['ip'], network.get('port', 8000),
                      network.get('http_port', 8003))[0].encode('utf-8')
    updated = dict(body, sha256=_digest(content))
    if projection == 'owned_hy_gateway':
        updated['canonical_sha256'] = _digest(after)
    new_marker = json.dumps(updated, indent=2).encode('utf-8')
    return dict(project=project, source=source, target=target, marker=marker,
                before=before, after=after, old=old, old_marker=old_marker,
                content=content, new_marker=new_marker)


def verify_copy(plan, *, canonical_written=False):
    if plan is None:
        return
    if (plan['source'].read_bytes() != plan['after' if canonical_written else 'before']
            or plan['target'].read_bytes() != plan['old']
            or plan['marker'].read_bytes() != plan['old_marker']):
        raise ValueError('network_copy_changed_concurrently')


def backup_copy(plan):
    if plan is None:
        return
    verify_copy(plan)
    if plan['old'] == plan['content'] and plan['old_marker'] == plan['new_marker']:
        return
    name = 'network-' + uuid4().hex
    for suffix, content in (('.yaml', plan['old']), ('.json', plan['old_marker'])):
        path = plan['project'] / 'local/archive/config-generated' / (name + suffix)
        _safe(path, plan['project'])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(content)
        if _digest(path.read_bytes()) != _digest(content):
            raise ValueError('network_copy_backup_failed')
    verify_copy(plan)


def write_copy(plan):
    if plan is None:
        return
    verify_copy(plan, canonical_written=True)
    if plan['content'] != plan['old']:
        _atomic(plan['target'], plan['content'])
    if plan['new_marker'] != plan['old_marker']:
        _atomic(plan['marker'], plan['new_marker'])
    if (plan['target'].read_bytes() != plan['content'] or plan['marker'].read_bytes() != plan['new_marker']
            or plan['source'].read_bytes() != plan['after']):
        raise ValueError('network_copy_update_unconfirmed')
