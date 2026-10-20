"""正式启动/私有provider/能力回调的纯合成检查；不读配置、不加载模型。"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / 'scripts/development/xiaozhi'


@pytest.fixture
def launch(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    for name in ('LONGMEMORY_VOICE_PREEMPTIVE_ENABLED', 'LONGMEMORY_TURN_END_MODE',
                 'LONGMEMORY_COSY_DELIVERY_MODE', 'LONGMEMORY_MEMORY_BACKEND'):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location('ai_proposal_bootstrap', SCRIPTS / 'launch_with_memory.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_off_never_imports_adapter_or_patches_classes(launch, monkeypatch):
    class Connection:
        pass
    before = dict(vars(Connection))
    monkeypatch.setitem(sys.modules, 'voice_proposal_adapter', None)
    assert launch.install_voice_proposal_policy(Connection) is None
    assert dict(vars(Connection)) == before


@pytest.mark.parametrize('intent,functions,configured,handler,expected', [
    ('nointent', False, False, False, (False, False)),
    ('nointent', True, True, False, (True, True)),
    ('function_call', True, False, True, (True, False)),
    ('function_call', True, True, True, (True, True)),
    ('nointent', False, True, False, None),
    ('intent_llm', True, False, True, None),
    ('unknown', True, False, False, None),
])
def test_capabilities_use_actual_paths_without_executing_tools(launch, monkeypatch, intent, functions, configured, handler, expected):
    calls = []
    provider = NS(response=lambda *_a, **_k: pytest.fail('no provider call in preview'))
    if functions:
        provider.response_with_functions = lambda *_a, **_k: pytest.fail('no tools in preview')
    conn = NS(intent_type=intent, llm=provider)
    if handler:
        conn.func_handler = NS(get_functions=lambda: pytest.fail('do not populate tool cache'))
    import voice_web_search as web
    monkeypatch.setattr(web, 'load_config', lambda: NS(provider='tavily' if configured else 'disabled'))
    def preview(connection, raw, **kwargs):
        calls.append((connection, raw, kwargs))
        return 'plan'
    monkeypatch.setitem(sys.modules, 'voice_proposal_adapter', NS(preview_native_input=preview))
    raw = '{"content":"合成输入","emotion":"calm"}'
    result = launch.preview_voice_proposal_input(conn, raw)
    if expected is None:
        assert result is None and not calls
    else:
        assert result == 'plan'
        assert calls == [(conn, raw, dict(tools_required=expected[0], web_configured=expected[1]))]


def test_private_observed_provider_is_bound_without_mutating_shared_provider(launch):
    from voice_latency import _ObservedLLM
    original, private, calls = NS(identity='shared'), NS(identity='private'), []
    adapter = NS(bind_provider=lambda conn, provider: calls.append((conn, provider)) or private)
    connection = NS(_longmemory_proposal_adapter=adapter)
    observed = _ObservedLLM(connection, original)
    assert observed._provider is private and calls == [(connection, original)]
    assert vars(original) == {'identity': 'shared'}
    assert _ObservedLLM(NS(), original)._provider is original


def test_enabled_install_passes_real_callbacks_not_reconstructed_metadata(launch, monkeypatch):
    values = {}
    def install(*args, **kwargs):
        values.update(args=args, kwargs=kwargs)
        return 'adapter'
    monkeypatch.setitem(sys.modules, 'voice_proposal_adapter', NS(install_voice_proposal_adapter=install))
    connection, fun, base, rpc = object(), object(), object(), object()
    assert launch.install_voice_proposal_policy(connection, enabled=True, fun_local=fun, asr_base=base, rpc_factory=rpc) == 'adapter'
    assert values == {'args': (connection, fun, base), 'kwargs': dict(enabled=True,
        preview_effective_input=launch.preview_voice_proposal_input,
        formal_metadata=launch.voice_proposal_formal_metadata, rpc_factory=rpc)}


@pytest.mark.parametrize('arguments', [
    ['--enable-voice-preemptive', '--voice-mode', 'doubao_realtime'],
    ['--enable-voice-preemptive', '--voice-latency-mode', 'original'],
])
def test_unsupported_modes_refuse_before_loading_vendor_or_private_configuration(launch, monkeypatch, arguments):
    monkeypatch.setitem(sys.modules, 'core.connection', None)
    monkeypatch.setattr(sys, 'argv', ['launch_with_memory.py', *arguments])
    with pytest.raises(SystemExit) as error:
        launch.main()
    assert error.value.code == 2


@pytest.mark.parametrize('enable', ['off', 'cli', 'environment'])
def test_formal_main_adapter_wraps_all_chat_paths_before_connections_are_created(launch, monkeypatch, tmp_path, enable):
    calls = []
    connection, base, fun = type('Connection', (), {}), object(), object()
    receive, send = NS(), NS()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['launch_with_memory.py'] + (['--enable-voice-preemptive'] if enable == 'cli' else []))
    if enable == 'environment':
        monkeypatch.setenv('LONGMEMORY_VOICE_PREEMPTIVE_ENABLED', '1')
    modules = {
        'core': NS(handle=NS(receiveAudioHandle=receive, sendAudioHandle=send)),
        'core.connection': NS(ConnectionHandler=connection),
        'core.handle': NS(receiveAudioHandle=receive, sendAudioHandle=send),
        'core.handle.receiveAudioHandle': receive,
        'core.providers.asr': NS(base=base, fun_local=fun),
        'core.providers.memory.longmemory.longmemory': NS(MemoryProvider=object),
        'direct_ws_v2': NS(install_direct_ws_v2=lambda *_a: None),
        'fast_voice_responses': NS(install_fast_voice_responses=lambda *_a: None),
        'voice_input_latency': NS(install_voice_input_latency=lambda *_a: calls.append('input')),
        'voice_latency': NS(install_voice_latency=lambda *_a: calls.append('observer'), install_audio_send_observer=lambda: None),
        'voice_prediction': NS(install_voice_prediction_shadow=lambda *_a: None),
        'voice_persistent_session': NS(install_persistent_device_session=lambda *_a: None),
        'voice_waiting': NS(install_waiting_sender=lambda *_a: None),
    }
    for name, value in modules.items():
        monkeypatch.setitem(sys.modules, name, value)
    monkeypatch.setattr(launch, 'isolate_memory_initialization', lambda *_a: None)
    monkeypatch.setattr(launch, 'install_pipeline_latency_policy', lambda *_a, **_k: calls.append('prefetch'))
    monkeypatch.setattr(launch, 'install_advanced_voice_policy', lambda *_a, **_k: calls.append('turn'))
    def adapter(cls, **kwargs):
        assert cls is connection and kwargs == dict(enabled=True, fun_local=fun, asr_base=base)
        calls.append('adapter')
    monkeypatch.setattr(launch, 'install_voice_proposal_policy', adapter)
    monkeypatch.setattr(launch, 'install_answer_completion', lambda *_a: calls.append('completion'))
    monkeypatch.setattr(launch, 'install_internal_end_prompt_boundary', lambda *_a: None)
    monkeypatch.setattr(launch.runpy, 'run_path', lambda *_a, **_k: calls.append('run'))
    launch.main()
    assert calls == ['input', 'prefetch', 'turn', 'observer', 'completion', *(['adapter'] if enable != 'off' else []), 'run']
