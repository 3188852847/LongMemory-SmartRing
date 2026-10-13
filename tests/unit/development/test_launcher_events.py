import importlib.util
import json
from pathlib import Path


def _events(root):
    file = Path(__file__).resolve().parents[3] / 'scripts/development/launcher/events.py'
    spec = importlib.util.spec_from_file_location('launcher_events_test', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LauncherEvents(root)


def test_only_whitelisted_operation_fields_are_logged(tmp_path):
    events = _events(tmp_path)
    events.record('synthetic-id', event='request_result', status=409,
                  action='secret-input-not-a-command', phase='not-a-state')
    body = json.loads(events.path.read_text(encoding='utf-8'))
    assert set(body) == {'time', 'request_id', 'event', 'status'}
    assert 'secret-input' not in events.path.read_text(encoding='utf-8')


def test_polling_records_phase_changes_once(tmp_path):
    events = _events(tmp_path)
    for phase in ['stopped', 'stopped', 'starting', 'starting', 'failed']:
        events.record('synthetic-id', event='phase_changed', phase=phase)
    rows = [json.loads(line) for line in events.path.read_text(encoding='utf-8').splitlines()]
    assert [row['phase'] for row in rows] == ['stopped', 'starting', 'failed']
