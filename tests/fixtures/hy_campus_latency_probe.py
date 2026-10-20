"""显式双源码、合成库、共享至多8次调用的校园Memory探针；不启动TTS/设备。

真实执行必须同时给 --mode campus --execute-campus；loopback仅供本地替身测试。
调用者负责受控维护窗口。工具不停止日用服务、不写其配置、数据或官方付费账本。
"""

import argparse
import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
from time import perf_counter
from urllib import request as urlrequest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hy_campus_probe_support import calls_snapshot, halt_calls, limited_campus_calls


TOOL = Path(__file__).resolve()
TOOL_ROOT = TOOL.parents[2]
PROCESS_OWNER = TOOL_ROOT / 'scripts/development/launcher/winjob.py'
QUERIES = ('合成测试用户喜欢无糖乌龙茶。请只回复：记住了。',
           '合成测试用户喜欢什么茶？只用一句短话回答。')
ROLE = '这是隔离合成验收。只根据给出的记忆上下文简短回答，不执行工具或外部操作。'
FORBIDDEN_PORTS = {8000, 8002, 8003, 8766, 8767, 8768, 18000, 18003, 18767, 18768, 18769, 18770}


class ProbeFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ProbeFailure(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path, maximum=65536):
    path = unlinked(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, 'probe_input_file_invalid')
    return json.loads(path.read_text(encoding='utf-8'))


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, allow_nan=False)


def unlinked(path):
    path = Path(path).absolute()
    require(path.resolve() == path, 'probe_linked_path')
    for parent in (path, *path.parents):
        require(not parent.is_symlink() and not parent.is_junction(), 'probe_linked_path')
    return path


def source_identity(root):
    root = unlinked(root)
    def git(*arguments):
        return subprocess.check_output(['git', '-C', str(root), *arguments], stderr=subprocess.DEVNULL).strip()
    require(not git('status', '--porcelain', '--untracked-files=normal'), 'probe_source_not_clean')
    source = root / 'src/longmemory'
    require((source / 'methods/hy_memory/worker.py').is_file(), 'probe_source_missing')
    sha = hashlib.sha256()
    files = sorted(source.rglob('*.py')) + sorted((root / 'scripts/development/xiaozhi').rglob('*.py'))
    for path in files:
        unlinked(path)
        sha.update(path.relative_to(root).as_posix().encode() + b'\0')
        sha.update(path.read_bytes().replace(b'\r\n', b'\n'))
    return {'head': git('rev-parse', 'HEAD').decode(), 'tree': git('rev-parse', 'HEAD^{tree}').decode(),
            'python_source_sha256': sha.hexdigest()}


def validate_output(path, allowed):
    path, allowed = unlinked(path), unlinked(allowed)
    require(path.is_relative_to(allowed) and path != allowed and not path.exists(), 'probe_new_output_required')
    return path


def campus_policy(owner, model):
    policy = read_json(owner / 'local/config/hy-memory/provider-policy.json', 8192)
    required = {'version', 'profile', 'billing_mode', 'personal_cost_micro_cny', 'source', 'confirmed_date',
                'endpoint_sha256', 'request_model', 'credential_sha256', 'ledger_path'}
    require(isinstance(policy, dict) and set(policy) == required and type(policy['version']) is int
        and policy['version'] == 1 and policy['profile'] == 'campus'
        and policy['billing_mode'] == 'owner_confirmed_free' and type(policy['personal_cost_micro_cny']) is int
        and policy['personal_cost_micro_cny'] == 0 and policy['source'] == 'owner_confirmation'
        and policy['confirmed_date'] == '2026-10-19'
        and policy['endpoint_sha256'] == digest(model.base_url.encode())
        and policy['credential_sha256'] == digest(model.api_key.encode())
        and policy['request_model'] == model.model, 'probe_campus_policy_mismatch')
    # 仅核对旧路径语法；不打开所有者的任何账本。
    from longmemory.infrastructure.config.hy_deployment import _path
    _path(owner, policy['ledger_path'], parent='data/databases')
    return {**policy, 'ledger_path': 'data/databases/probe-campus-calls.sqlite3'}


def preflight(arguments):
    identities = {name: source_identity(getattr(arguments, name + '_root')) for name in ('baseline', 'candidate')}
    unlinked(arguments.owner_root)
    sys.path.insert(0, str(arguments.candidate_root / 'src'))
    from longmemory.methods.hy_memory.model_gateway import selected_model
    from longmemory.methods.hy_memory.settings import HySettings, Endpoint
    from longmemory.infrastructure.config.hy_deployment import load_hy_deployment
    model, model_identity = selected_model(arguments.owner_root)
    require(model_identity.get('profile') == 'campus', 'probe_campus_only')
    policy = campus_policy(arguments.owner_root, model)
    sdk = unlinked(arguments.sdk_python)
    require(sdk.is_file(), 'probe_sdk_python_missing')
    if arguments.mode == 'campus':
        require(arguments.execute_campus, 'probe_explicit_campus_execution_required')
        deployment = load_hy_deployment(arguments.owner_root)
        require(deployment.python.resolve() == sdk and deployment.settings.llm.model == model.model,
                'probe_selected_sdk_or_model_mismatch')
        prototype = deployment.settings
        require(prototype.managed_gateway and prototype.network_authorized
            and prototype.model_mode == 'disabled' and prototype.embedding_dimensions == 512,
            'probe_managed_configuration_required')
    else:
        from urllib.parse import urlsplit
        url = urlsplit(model.base_url)
        require(url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port not in FORBIDDEN_PORTS
            and url.port is not None, 'probe_loopback_endpoint_required')
        encoder_identity = 'f' * 64
        provider_identity = digest(json.dumps({'model': model_identity, 'embedding': encoder_identity}, sort_keys=True).encode())
        prototype = HySettings(user_id='probe-synthetic', embedding_dimensions=512,
            llm=Endpoint('http://127.0.0.1:9/hy/v1', model.model, 'synthetic-local', True),
            embedding=Endpoint('http://127.0.0.1:9/hy/v1', encoder_identity, 'synthetic-local', True),
            network_authorized=True, managed_gateway=True, provider_identity=provider_identity,
            max_external_requests=32, timeout_seconds=10)
    prototype = replace(prototype, user_id='campus-latency-synthetic', agent_id='campus-latency-synthetic')
    proofs = {name: read_json(getattr(arguments, name + '_proof'), 8192) for name in ('baseline', 'candidate')}
    for name, proof in proofs.items():
        sha = management_identity(getattr(arguments, name + '_root'))
        require(isinstance(proof, dict) and set(proof) == {'sdk_version', 'rpc_source_sha256',
            'real_sdk_rpc_verified', 'semantic_background_writes_disabled'} and proof['sdk_version'] == '2.0.3'
            and proof['rpc_source_sha256'] == sha and proof['real_sdk_rpc_verified'] is True
            and proof['semantic_background_writes_disabled'] is True, 'probe_verified_management_receipts_required')
    protected = ('local/config/.env', 'local/config/preferences/model-profile.json',
                 'local/config/hy-memory/provider-policy.json', 'local/config/hy-memory/deployment.json',
                 'local/config/hy-memory/settings.json', 'local/config/hy-memory/management-verification.json')
    hashes = {name: digest((arguments.owner_root / name).read_bytes()) for name in protected
              if (arguments.owner_root / name).is_file()}
    return {'identities': identities, 'model': asdict(model), 'model_identity': model_identity,
            'prototype': prototype.wire(), 'policy': policy, 'proofs': proofs, 'protected': hashes,
            'sdk_python_sha256': digest(sdk.read_bytes())}


def management_identity(root):
    code = "import sys;sys.path.insert(0,sys.argv[1]);from longmemory.methods.hy_memory.assembly import management_primitives_identity;print(management_primitives_identity())"
    result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', code, str(root / 'src')],
        cwd=root, capture_output=True, timeout=20)
    sha = result.stdout.decode('ascii', errors='ignore').strip()
    require(result.returncode == 0 and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha),
            'probe_management_identity_unavailable')
    return sha


def protected_unchanged(owner, hashes):
    require(all((owner / name).is_file() and digest((owner / name).read_bytes()) == value
                for name, value in hashes.items()), 'probe_owner_configuration_changed')


def child_process(configuration, *, timeout):
    """子进程先等stdin；加入自有Job之后才许可它创建SDK后代。"""
    env = {key: value for key, value in os.environ.items() if key.upper() in
           {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE'}}
    root = Path(configuration['arm_directory'])
    home = root / 'home'
    home.mkdir()
    env.update(HOME=str(home), USERPROFILE=str(home), TEMP=str(home), TMP=str(home),
        HF_HOME=str(home / 'huggingface'), XDG_CACHE_HOME=str(home / 'cache'),
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
        PYTHONIOENCODING='utf-8', PYTHON_DOTENV_DISABLED='1')
    job = None
    if os.name == 'nt':
        spec = importlib.util.spec_from_file_location('probe_owned_job', PROCESS_OWNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        job = module.Job()
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8', str(TOOL), '--worker'],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
    except BaseException:
        if job is not None:
            job.close()
        raise
    try:
        if job is not None:
            job.assign(process)
        output, _ = process.communicate(json.dumps(configuration).encode(), timeout=timeout)
        require(len(output) <= 65536, 'probe_worker_response_too_large')
        result = json.loads(output)
        require(process.returncode == 0 and result.get('status') == 'completed', 'probe_arm_failed')
        return result
    finally:
        failed = False
        try:
            if job is not None:
                job.close()
            elif process.poll() is None:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
        except BaseException:
            failed = True
        alive = True
        try:
            alive = process.poll() is None
        except BaseException:
            failed = True
        if alive:
            try:
                process.kill()
            except BaseException:
                failed = True
        try:
            process.wait(timeout=5)
        except BaseException:
            failed = True
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except BaseException:
                failed = True
        if failed:
            raise ProbeFailure('probe_owned_exit_unconfirmed') from None


class AnswerSink:
    """只保留本轮答案供原完成回执使用；收据仅含时长/长度，不保存答案。"""
    def __init__(self):
        self.wfile = self
        self.status = None
        self.close_connection = False
        self.buffer = b''
        self.event_lines = []
        self.answer = ''
        self.started = perf_counter()
        self.first_text_ms = None
        self.done = False

    def send_response(self, status): self.status = status
    def send_header(self, *args): pass
    def end_headers(self): pass
    def flush(self): pass
    def respond(self, status, body): self.status = status

    def write(self, data):
        self.buffer += data
        require(len(self.buffer) <= 131072, 'probe_sse_line_too_large')
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line.strip():
                self.event_lines.append(line)
                require(sum(map(len, self.event_lines)) <= 131072, 'probe_sse_event_too_large')
                continue
            payload = b'\n'.join(line[5:].strip() for line in self.event_lines if line.startswith(b'data:'))
            self.event_lines.clear()
            if payload == b'[DONE]':
                self.done = True
            elif payload:
                value = json.loads(payload)
                for choice in value.get('choices') or ():
                    content = (choice.get('delta') or {}).get('content')
                    if isinstance(content, str) and content:
                        if self.first_text_ms is None:
                            self.first_text_ms = round((perf_counter() - self.started) * 1000, 3)
                        self.answer += content
                        require(len(self.answer) <= 2000, 'probe_answer_too_large')
        return len(data)


def prepare_http(url, token, query, index):
    payload = {'version': 1, 'query': query, 'client_round_id': ('a' if index == 0 else 'b') * 32,
               'session_id': 'c' * 32}
    req = urlrequest.Request(url, data=json.dumps(payload).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, 'X-Memory-Observe': '1'})
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
    started = perf_counter()
    with opener.open(req, timeout=20) as response:
        content = response.read(65537)
        require(response.status == 200 and len(content) <= 65536, 'probe_prepare_failed')
        result = json.loads(content)
        observation = response.headers.get('X-Memory-Observation')
    return result, round((perf_counter() - started) * 1000, 3), observation


async def run_arm(config):
    source_root, root = Path(config['source_root']), Path(config['arm_directory'])
    require(source_identity(source_root) == config['source_identity'], 'probe_source_changed')
    sys.path.insert(0, str(source_root / 'src'))
    import longmemory
    require(Path(longmemory.__file__).resolve().is_relative_to(source_root / 'src'), 'probe_import_source_mismatch')
    from aiohttp import web
    from longmemory.bootstrap import build_hy_memory_runtime
    from longmemory.bootstrap_hy_daily import OwnedHyModels, load_daily_encoder
    from longmemory.methods.hy_memory.model_gateway import ModelGateway
    from longmemory.methods.hy_memory.settings import HySettings, Endpoint
    from longmemory.methods.hy_memory.assembly import management_primitives_identity
    from longmemory.infrastructure.config.settings import ModelSettings
    from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
    from longmemory.entrypoints.api.chat_backend import ChatBackend
    from longmemory.entrypoints.api.routes.memory_runtime import register_memory_runtime_routes
    from longmemory.entrypoints.api.security import Sessions, security_middleware
    from longmemory.adapters.llm.fake import FakeAnswerGenerator
    from longmemory.application.round_screen_turns import memory_receipt
    runtime = backend = gateway = runner = None
    rows, captured = [], []
    model = ModelSettings(**config['model'])
    budget = limited_campus_calls(FreeCampusCalls, Path(config['ledger']), config['policy'],
        arm=config['arm'], limit=config['request_limit'])
    try:
        prototype = HySettings.from_wire(config['prototype'])
        # 在任何模型/编码器加载前，核验该臂自己的真实SDK管理验收证明。
        proof = config['management_proof']
        require(set(proof) == {'sdk_version', 'rpc_source_sha256', 'real_sdk_rpc_verified',
                'semantic_background_writes_disabled'} and proof['sdk_version'] == '2.0.3'
                and proof['rpc_source_sha256'] == management_primitives_identity()
                and proof['real_sdk_rpc_verified'] is True and proof['semantic_background_writes_disabled'] is True,
                'probe_management_proof_mismatch')
        encoder_started = perf_counter()
        if config['mode'] == 'campus':
            encoder = load_daily_encoder(Path(config['owner_root']))
        else:
            class Encoder:
                identity = 'f' * 64
                def encode_query(self, text): return [1.0] + [0.0] * 511
                def encode_documents(self, texts): return [self.encode_query(text) for text in texts]
            encoder = Encoder()
        encoder_ms = round((perf_counter() - encoder_started) * 1000, 3)
        provider = digest(json.dumps({'model': config['model_identity'], 'embedding': encoder.identity}, sort_keys=True).encode())
        require(prototype.embedding.model == encoder.identity and prototype.provider_identity == provider,
                'probe_model_resource_identity_mismatch')
        gateway = ModelGateway(settings=model, budget=budget, encoder=encoder, free_policy_verified=True)
        gateway.__enter__()
        settings = replace(prototype, llm=Endpoint(gateway.base + '/hy/v1', model.model, gateway.token, True),
            embedding=Endpoint(gateway.base + '/hy/v1', encoder.identity, gateway.token, True))
        started = perf_counter()
        runtime = build_hy_memory_runtime(settings=settings, state_directory=root / 'data/memory/synthetic',
            source_path=root / 'data/databases/synthetic-source.sqlite3', create=True,
            python=Path(config['sdk_python']), expected_python_version='3.12.13', management_verification=proof)
        sdk_initialize_ms = round((perf_counter() - started) * 1000, 3)
        runtime.attach_model_service(OwnedHyModels(gateway, budget))
        if settings.include_profile:
            require(runtime.administer_extension('hy_memory', 'workspace').get('profile'), 'probe_profile_scope_unproven')
        class Backend(ChatBackend):
            def prepare_round_screen_user(self, *args, **kwargs):
                value = super().prepare_round_screen_user(*args, **kwargs)
                captured.append(value[0])
                return value
        backend = Backend(runtime.database, FakeAnswerGenerator(), runtime=runtime)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        require(port not in FORBIDDEN_PORTS, 'probe_daily_port_refused')
        token = secrets.token_hex(32)
        app = web.Application(middlewares=[security_middleware(f'127.0.0.1:{port}', Sessions(), token)])
        register_memory_runtime_routes(app, backend)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.SockSite(runner, sock).start()
        for index, query in enumerate(QUERIES[:config['rounds_per_arm']]):
            require(not calls_snapshot(Path(config['ledger']))['halted'], 'probe_gate_halted')
            start = perf_counter()
            body, prepare_ms, observation_header = await asyncio.to_thread(prepare_http,
                f'http://127.0.0.1:{port}/api/internal/memory/prepare', token, query, index)
            require(len(captured) == index + 1, 'probe_prepare_count_mismatch')
            prepared = captured[index]
            require(runtime.source_detail(prepared.event.event_id)['content'] == query, 'probe_archive_missing')
            require(prepared.memory_command is None and body.get('command_reply') is None,
                    'probe_unexpected_control_command')
            require(not body.get('external_model_pause'), 'probe_model_paused')
            if index:
                require('无糖乌龙茶' in prepared.support.context and any(
                    captured[0].event.event_id in (item.source_event_ids or ()) for item in prepared.support.retrieved),
                    'probe_recall_or_source_missing')
            sink = AnswerSink()
            answer_body = {'model': model.model, 'messages': [{'role': 'system',
                'content': ROLE + '\n记忆上下文：' + body['context']}, {'role': 'user', 'content': query}],
                'max_tokens': min(64, model.max_tokens), 'stream': True}
            await asyncio.to_thread(gateway.stream, answer_body, sink)
            answer_finished = perf_counter()
            snapshot = calls_snapshot(Path(config['ledger']))
            require(sink.status == 200 and sink.done and sink.answer.strip() and not snapshot['unknown_or_inflight']
                    and not snapshot['halted'], 'probe_answer_or_usage_incomplete')
            if index == 0:
                complete_started = perf_counter()
                await asyncio.to_thread(runtime.complete_round_screen, turn_id=prepared.event.event_id,
                    answer=sink.answer, receipt=memory_receipt(prepared), client_round_id='a' * 32)
                await asyncio.to_thread(runtime.wait_for_deferred_observations)
                complete_ms = round((perf_counter() - complete_started) * 1000, 3)
                require(runtime.source_status(prepared.event.event_id)['state'] == 'completed', 'probe_extraction_not_completed')
            else:
                runtime.cancel_round_screen(prepared.event.event_id, reason='cancelled', client_round_id='b' * 32)
                complete_ms = None
            require(not calls_snapshot(Path(config['ledger']))['unknown_or_inflight']
                and not calls_snapshot(Path(config['ledger']))['halted'], 'probe_call_state_uncertain')
            observation = None
            if observation_header:
                from longmemory.methods.hy_memory.observation import valid_snapshot
                value = json.loads(observation_header)
                require(len(observation_header) <= 4096 and valid_snapshot(value, ('a' if index == 0 else 'b') * 32),
                        'probe_observation_invalid')
                observation = value['stages']
            row = {'round': index + 1, 'condition': 'first_empty' if not index else 'warm_seed_recall',
                'prepare_http_ms': prepare_ms, 'prepare_timings_ms': body['timings_ms'], 'sdk_observation': observation,
                'answer_first_text_ms': sink.first_text_ms, 'prepare_to_answer_first_text_ms':
                    round((sink.started - start) * 1000 + sink.first_text_ms, 3) if sink.first_text_ms is not None else None,
                'answer_total_ms': round((answer_finished - sink.started) * 1000, 3), 'completion_and_extract_ms': complete_ms,
                'round_total_ms': round((perf_counter() - start) * 1000, 3), 'retrieved_count': len(prepared.support.retrieved),
                'answer_characters': len(sink.answer), 'prior_round_source_recalled': True if index else None,
                'completion': 'completed_and_extracted' if not index else 'cancelled_after_sampling'}
            write_new(root / f'round-{index + 1}.json', row)
            rows.append(row)
        require(source_identity(source_root) == config['source_identity'], 'probe_source_changed')
        diagnostics = runtime._method.engine.sdk_call('diagnostics')
        return {'status': 'completed', 'arm': config['arm'], 'source': config['source_identity'],
                'encoder_initialize_ms': encoder_ms, 'sdk_initialize_ms': sdk_initialize_ms,
                'settings_identity': settings.identity(), 'management_primitives_sha256': management_primitives_identity(),
                'rounds': rows, 'sdk_diagnostics': {key: diagnostics[key]
                    for key in ('actual_sdk_version', 'sdk_python')}, 'mode': config['mode'],
                'scope': 'CPU Memory/internal HTTP + campus SSE first text; no ASR/TTS/provider handoff/device playback'}
    finally:
        if runner is not None:
            await runner.cleanup()
        if backend is not None:
            backend.close()
        elif runtime is not None:
            runtime.close()
        if gateway is not None:
            gateway.close()


def run(arguments):
    require(1 <= arguments.request_limit <= 8 and arguments.rounds_per_arm in (1, 2), 'probe_bounds_invalid')
    require(30 <= arguments.timeout_seconds <= 300, 'probe_timeout_invalid')
    output = validate_output(arguments.output, TOOL_ROOT / 'data/test-tmp')
    config = preflight(arguments)
    # preflight只读；成功之后才排他创建全部合成证据。
    output.mkdir(parents=True, exist_ok=False)
    policy = config['policy']
    from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
    ledger = output / policy['ledger_path']
    limited_campus_calls(FreeCampusCalls, ledger, policy, create=True, limit=arguments.request_limit)
    manifest = {'version': 1, 'status': 'running', 'mode': arguments.mode, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'source_roots': config['identities'], 'order': arguments.arm_order.split(','), 'request_limit': arguments.request_limit,
        'rounds_per_arm': arguments.rounds_per_arm, 'tool_sha256': digest(TOOL.read_bytes()),
        'gate_sha256': digest(TOOL.with_name('hy_campus_probe_support.py').read_bytes()),
        'process_owner_sha256': digest(PROCESS_OWNER.read_bytes()),
        'sdk_python_sha256': config['sdk_python_sha256'], 'protected_config_sha256': config['protected'],
        'model_identity': config['model_identity'], 'query_sha256': [digest(q.encode()) for q in QUERIES],
        'role_sha256': digest(ROLE.encode()), 'official_budget_opened': False, 'personal_state_opened': False,
        'gpu_or_tts_started': False, 'limits_enforced_before_provider_request': True}
    write_new(output / 'plan.json', manifest)
    results = {}
    error = None
    try:
        for arm in manifest['order']:
            require(digest(TOOL.read_bytes()) == manifest['tool_sha256']
                and digest(TOOL.with_name('hy_campus_probe_support.py').read_bytes()) == manifest['gate_sha256']
                and digest(PROCESS_OWNER.read_bytes()) == manifest['process_owner_sha256'],
                'probe_tool_changed')
            protected_unchanged(arguments.owner_root, config['protected'])
            require(source_identity(getattr(arguments, arm + '_root')) == config['identities'][arm], 'probe_source_changed')
            root = output / arm
            root.mkdir()
            worker_config = {key: config[key] for key in ('model', 'model_identity', 'prototype', 'policy')}
            worker_config.update(arm=arm, source_root=str(getattr(arguments, arm + '_root')),
                source_identity=config['identities'][arm], arm_directory=str(root), ledger=str(ledger),
                owner_root=str(arguments.owner_root), sdk_python=str(arguments.sdk_python),
                management_proof=config['proofs'][arm], mode=arguments.mode,
                request_limit=arguments.request_limit, rounds_per_arm=arguments.rounds_per_arm)
            results[arm] = child_process(worker_config, timeout=arguments.timeout_seconds)
            write_new(output / (arm + '-receipt.json'), results[arm])
            require(not calls_snapshot(ledger)['halted'] and not calls_snapshot(ledger)['unknown_or_inflight'],
                    'probe_uncertain_call_state')
        protected_unchanged(arguments.owner_root, config['protected'])
        require(digest(TOOL.read_bytes()) == manifest['tool_sha256']
            and digest(TOOL.with_name('hy_campus_probe_support.py').read_bytes()) == manifest['gate_sha256']
            and digest(PROCESS_OWNER.read_bytes()) == manifest['process_owner_sha256'],
            'probe_tool_changed')
        require(all(source_identity(getattr(arguments, arm + '_root')) == config['identities'][arm]
                    for arm in ('baseline', 'candidate')), 'probe_source_changed')
        with sqlite3.connect(ledger.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            require(connection.execute('SELECT COUNT(*) FROM gateway_results').fetchone()[0]
                == calls_snapshot(ledger)['attempt_count'], 'probe_gateway_diagnostics_missing')
    except BaseException as failure:
        error = ('cancelled' if isinstance(failure, KeyboardInterrupt) else 'timeout'
                 if isinstance(failure, subprocess.TimeoutExpired) else 'validation_failed'
                 if isinstance(failure, ProbeFailure) and str(failure) in {
                     'probe_source_changed', 'probe_owner_configuration_changed', 'probe_tool_changed'} else 'probe_failed')
        halt_calls(ledger, error)
    receipt = {**manifest, 'status': 'completed' if error is None else 'failed', 'error': error,
        'calls': calls_snapshot(ledger), 'completed_arms': list(results),
        'finished_utc': datetime.now(timezone.utc).isoformat(), 'n_per_condition': 1,
        'performance_claim': 'single paired cold/warm sample only; no P95 or device E2E claim'}
    write_new(output / 'receipt.json', receipt)
    return receipt


def main():
    if sys.argv[1:] == ['--worker']:
        configuration = json.loads(sys.stdin.buffer.read(262145))
        try:
            result = asyncio.run(run_arm(configuration))
            print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        except BaseException:
            halt_calls(Path(configuration['ledger']), 'probe_failed')
            print(json.dumps({'status': 'failed', 'error': 'probe_arm_failed'}))
            raise SystemExit(1)
        return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline-root', 'candidate-root', 'owner-root', 'sdk-python', 'baseline-proof', 'candidate-proof', 'output'):
        parser.add_argument('--' + name, required=True, type=lambda value: Path(value).absolute())
    parser.add_argument('--mode', choices=('campus', 'loopback'), required=True)
    parser.add_argument('--execute-campus', action='store_true')
    parser.add_argument('--request-limit', type=int, default=8)
    parser.add_argument('--rounds-per-arm', type=int, default=2)
    parser.add_argument('--arm-order', choices=('baseline,candidate', 'candidate,baseline'), default='baseline,candidate')
    parser.add_argument('--timeout-seconds', type=int, default=180)
    arguments = parser.parse_args()
    try:
        receipt = run(arguments)
    except BaseException:
        print(json.dumps({'status': 'refused', 'error': 'probe_preflight_or_evidence_failed'}))
        raise SystemExit(2)
    print(json.dumps({'status': receipt['status'], 'mode': receipt['mode'], 'calls': receipt['calls'],
                      'output': str(arguments.output)}, ensure_ascii=True))
    raise SystemExit(0 if receipt['status'] == 'completed' else 1)


if __name__ == '__main__':
    main()
