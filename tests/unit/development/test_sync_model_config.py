"""使用合成密钥验证模型配置同步，不接触真实 .env 或小智目录。"""
import importlib.util
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'scripts/development/xiaozhi'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('sync_model_config_test', SCRIPTS / 'sync_model_config.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
sys.path.pop(0)


def test_updates_only_model_fields_and_preserves_text(tmp_path):
    project = tmp_path / 'project'; server = tmp_path / 'server'
    project.mkdir(); (server / 'data').mkdir(parents=True)
    (project / '.env').write_text(
        'LONGMEMORY_LLM_BASE_URL=http://synthetic.local/tenant/v1\n'
        'LONGMEMORY_LLM_MODEL=synthetic-model\n'
        'LONGMEMORY_LLM_API_KEY=SYNTHETIC_SECRET_NEW\n', encoding='utf-8')
    old = ('# preserve comment\nselected_module:\n  LLM: CampusLLM\n'
           'LLM:\n  CampusLLM:\n    type: openai\n    base_url: "http://old.local/v1"\n'
           '    api_key: "SYNTHETIC_SECRET_OLD"\n    model_name: old-model\n'
           'unrelated:\n  keep: true\n')
    target = server / 'data/.config.yaml'; target.write_text(old, encoding='utf-8')
    result = module.update(project, server)
    updated = target.read_text(encoding='utf-8')
    parsed = yaml.safe_load(updated)
    assert '# preserve comment' in updated and 'unrelated:\n  keep: true' in updated
    assert parsed['LLM']['CampusLLM'] == {'type':'openai', 'base_url':'http://synthetic.local/tenant/v1',
        'api_key':'SYNTHETIC_SECRET_NEW', 'model_name':'synthetic-model'}
    assert result['runtime'] == 'unverified' and '.model-' in result['backup']
    assert (target.parent / result['backup']).read_text(encoding='utf-8') == old


@pytest.mark.parametrize('base', ['http://synthetic.local/v1/chat/completions', 'not-a-url'])
def test_rejects_non_base_endpoint(tmp_path, base):
    project = tmp_path / 'project'; server = tmp_path / 'server'
    project.mkdir(); (server / 'data').mkdir(parents=True)
    (project / '.env').write_text(
        f'LONGMEMORY_LLM_BASE_URL={base}\nLONGMEMORY_LLM_MODEL=x\nLONGMEMORY_LLM_API_KEY=x\n', encoding='utf-8')
    (server / 'data/.config.yaml').write_text(
        'selected_module: {LLM: CampusLLM}\nLLM: {CampusLLM: {type: openai, base_url: old, api_key: old, model_name: old}}\n', encoding='utf-8')
    with pytest.raises(ValueError): module.update(project, server)
