"""离线真实SDK进程基准；两臂新合成库，禁止网络，不衡量模型质量或语音端到端。

从V工作树使用主解释器运行，--output必须是data/test-tmp下不存在的唯一目录。
只读现有专属SDK解释器；所有SDK文件与原文账本写入显式合成目录。
"""

import argparse
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pathlib import Path
import statistics
import sqlite3
import sys
from types import SimpleNamespace
from time import perf_counter
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
FIXTURE = Path(__file__).resolve()
SDK_PYTHON = ROOT / 'local/runtime/hy-memory/.venv/Scripts/python.exe'


def source_identity():
    """运行中并行修改须显式标为不可比，不能混用两版代码生成降幅。"""
    digest = hashlib.sha256()
    for path in sorted((ROOT / 'src/longmemory').rglob('*.py')):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
    digest.update(FIXTURE.read_bytes().replace(b'\r\n', b'\n'))
    return digest.hexdigest()


def measured(function, *, observations, stage):
    from longmemory.methods.hy_memory.observation import Observation
    observation = Observation(uuid4().hex)
    started = perf_counter()
    with observation.activate():
        result = function()
    elapsed = round((perf_counter() - started) * 1000, 3)
    observations[stage] = observation.snapshot()['stages']
    return result, elapsed


def one_arm(directory, sdk_python, enabled):
    from longmemory.methods.hy_memory.assembly import assemble_hy_backend
    from longmemory.methods.hy_memory.process_client import HyProcessClient
    from longmemory.methods.hy_memory.settings import HySettings
    from longmemory.methods.contracts import MemoryEvent

    settings = HySettings(user_id='short-input-synthetic', model_mode='synthetic_transport')
    command = [str(sdk_python), '-I', '-B', '-X', 'utf8', str(FIXTURE), '--worker',
               '--fast-path', str(int(enabled))]
    def client_factory(root, *, create):
        return HyProcessClient(python=sdk_python, workspace=root, settings=settings,
                               create=create, command=command)
    def open_assembly(create):
        return assemble_hy_backend(settings=settings, state_directory=directory / 'engine',
            source_path=directory / 'sources.db', create=create, client_factory=client_factory)
    stages, observations = {}, {}
    def measure(stage, function):
        return measured(function, observations=observations, stage=stage)
    assembly, stages['initialize_ms'] = measure('initialize_ms', lambda: open_assembly(True))
    event = MemoryEvent('synthetic-event-1', 'user', '合成用户喜欢无糖乌龙茶',
                        datetime(2026, 1, 1, tzinfo=timezone.utc), 'synthetic-session')
    checks = {}
    try:
        method = assembly.method
        first, stages['first_empty_recall_ms'] = measure('first_empty_recall_ms', lambda: method.recall('合成用户喜欢什么饮料'))
        checks['empty_recall_empty'] = not first.retrieved
        _, stages['archive_ms'] = measure('archive_ms', lambda: method.archive(event))
        checks['original_saved_before_observe'] = method.source_detail(event.event_id)['content'] == event.content
        result, stages['observe_ms'] = measure('observe_ms', lambda: method.observe(event))
        checks['observe_completed'] = result.processing_status == 'completed'
        duplicate, stages['duplicate_observe_ms'] = measure('duplicate_observe_ms', lambda: method.observe(event))
        checks['duplicate_same_receipt'] = duplicate == result
        recalled, stages['recall_after_observe_ms'] = measure('recall_after_observe_ms', lambda: method.recall('合成用户喜欢什么饮料'))
        checks['retrieved_synthetic_fact'] = any(event.content in item.content for item in recalled.retrieved)
        checks['source_trace_present'] = any(event.event_id in (item.source_event_ids or ()) for item in recalled.retrieved)
        _, stages['repeated_recall_ms'] = measure('repeated_recall_ms', lambda: method.recall('合成用户喜欢什么饮料'))
        for index, query in enumerate(('请说出合成用户偏爱的茶', '合成用户喝哪种无糖饮料', '合成用户的饮品偏好是什么')):
            stage = 'warm_distinct_recall_' + str(index) + '_ms'
            support, stages[stage] = measure(stage, lambda: method.recall(query))
            checks['warm_distinct_retrieval_' + str(index)] = any(event.content in item.content for item in support.retrieved)
        diagnostic = method.engine.sdk_call('diagnostics')
        checks['zero_external_requests'] = diagnostic['external_http_attempts'] == 0
        checks['fast_path_matches_arm'] = diagnostic['short_embedding_input']['applied'] is enabled
        counts = {key: diagnostic[key] for key in ('external_http_attempts', 'simulated_model_requests',
            'short_embedding_input', 'actual_sdk_version', 'sdk_python', 'sdk_observation_applied', 'local_initialization')}
    finally:
        assembly.method.close()
    reopened, stages['reopen_ms'] = measure('reopen_ms', lambda: open_assembly(False))
    try:
        checks['original_survives_restart'] = reopened.method.source_detail(event.event_id)['content'] == event.content
        replay, stages['restart_duplicate_ms'] = measure('restart_duplicate_ms', lambda: reopened.method.observe(event))
        checks['restart_duplicate_same_receipt'] = replay == result
        recalled, stages['restart_recall_ms'] = measure('restart_recall_ms', lambda: reopened.method.recall('合成用户喜欢什么饮料'))
        checks['retrieval_survives_restart'] = any(event.content in item.content for item in recalled.retrieved)
        diagnostic = reopened.method.engine.sdk_call('diagnostics')
        checks['restart_zero_external_requests'] = diagnostic['external_http_attempts'] == 0
        counts['restart_simulated_model_requests'] = diagnostic['simulated_model_requests']
    finally:
        reopened.method.close()
    if not all(checks.values()):
        raise RuntimeError('hy_short_benchmark_validation_failed:' + ','.join(key for key, value in checks.items() if not value))
    return {'stages_ms': stages, 'observations': observations, 'checks': checks, 'counts': counts}


def overlay_comparison(output):
    """同一只读合成账本，对照改动前逐ID SQL与当前批读；不折算总轮延迟。"""
    from longmemory.methods.hy_memory.administration import HyAdministration
    method = SimpleNamespace(_client=None)
    admin = HyAdministration(method)
    admin._ledger_path = output / 'overlay-synthetic.sqlite3'
    with sqlite3.connect(admin._ledger_path) as db:
        db.execute('CREATE TABLE operations (item_id TEXT,source_event_id TEXT,state TEXT,action TEXT,occurred_at TEXT,request_id TEXT)')
        db.executemany('INSERT INTO operations VALUES (?,?,?,?,?,?)',
            [('item-' + str(i), 'source-' + str(i), 'completed', 'correct', '2026-01-01', str(i))
             for i in range(703)])
    def original(ids):
        result = {}
        for item_id in ids:
            with admin._ledger() as db:
                rows = db.execute('SELECT source_event_id,state,action FROM operations WHERE item_id=? '
                                  'ORDER BY occurred_at,request_id', (item_id,)).fetchall()
                result[item_id] = (tuple(dict.fromkeys(row[0] for row in rows
                    if row[1] == 'completed' and row[2] == 'correct')),
                    any(row[1] in {'running', 'uncertain'} for row in rows))
        return result
    report = {}
    for size in (1, 16, 128, 703):
        ids = tuple('item-' + str(i) for i in range(size))
        rows = {'baseline': [], 'optimized': []}
        for repetition in range(7):
            order = ('baseline', 'optimized') if repetition % 2 == 0 else ('optimized', 'baseline')
            for arm in order:
                start = perf_counter()
                value = original(ids) if arm == 'baseline' else admin.source_overlays(ids)
                rows[arm].append((perf_counter() - start) * 1000)
                assert value == {item: (('source-' + str(i),), False) for i, item in enumerate(ids)}
        report[str(size)] = {arm: {'p50_ms': round(statistics.median(values), 3),
            'max_ms': round(max(values), 3)} for arm, values in rows.items()}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fast-path', type=int, choices=(0, 1), help=argparse.SUPPRESS)
    parser.add_argument('--sdk-python', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repetitions', type=int, default=3)
    arguments = parser.parse_args()
    if arguments.worker:
        if arguments.fast_path is None:
            parser.error('worker requires explicit arm')
        from longmemory.methods.hy_memory.worker import ProtocolService, create_sdk, main as worker_main
        worker_main(service=ProtocolService(factory=partial(create_sdk,
            short_embedding_fast_path=bool(arguments.fast_path), prepare_local_backends=bool(arguments.fast_path))))
        return
    if arguments.sdk_python is None or arguments.output is None or not 1 <= arguments.repetitions <= 10:
        parser.error('explicit --sdk-python, unique --output and 1..10 repetitions required')
    sdk_python = arguments.sdk_python.resolve()
    if sdk_python != SDK_PYTHON.resolve() or not sdk_python.is_file():
        parser.error('only the existing V dedicated SDK interpreter is allowed')
    output = arguments.output.absolute()
    allowed = (ROOT / 'data/test-tmp').resolve()
    if (output.exists() or output.is_symlink() or output.resolve() != output
            or not output.is_relative_to(allowed) or output == allowed):
        parser.error('output must be a new non-linked child of V data/test-tmp')
    output.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now(timezone.utc).isoformat()
    rows = {'baseline': [], 'optimized': []}
    identities = [source_identity()]
    for repetition in range(arguments.repetitions):
        order = ('baseline', 'optimized') if repetition % 2 == 0 else ('optimized', 'baseline')
        for arm in order:
            directory = output / (arm + '-' + str(repetition))
            directory.mkdir()
            before = source_identity()
            row = one_arm(directory, sdk_python, arm == 'optimized')
            after = source_identity()
            identities.extend((before, after))
            row['source_before_sha256'], row['source_after_sha256'] = before, after
            rows[arm].append(row)
            with (output / (arm + '-' + str(repetition) + '.json')).open('x', encoding='utf-8') as stream:
                json.dump(row, stream, ensure_ascii=True, indent=2)
    summary = {'scope': 'offline synthetic CPU SDK; not real model, answer, GPU or E2E speed',
               'started_at_utc': started_at, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
               'repetitions': arguments.repetitions, 'source_unchanged': len(set(identities)) == 1,
               'source_sha256': identities[0], 'arms': {}}
    for arm, samples in rows.items():
        summary['arms'][arm] = {stage: {'p50_ms': statistics.median(sample['stages_ms'][stage] for sample in samples),
            'max_ms': max(sample['stages_ms'][stage] for sample in samples)} for stage in samples[0]['stages_ms']}
    summary['overlay_same_ledger_7_repetitions'] = overlay_comparison(output)
    summary['source_unchanged'] = summary['source_unchanged'] and source_identity() == identities[0]
    summary['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    with (output / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=True, indent=2)
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == '__main__':
    main()
