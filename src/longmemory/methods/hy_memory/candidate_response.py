"""候选请求的自有上游句柄；无直连、工具、正式归档或播放入口。"""

import asyncio
import hashlib
import json
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from .answer_content import FinalContent
from .prefix_cache import cache_evidence
from .provider_transport import finish_before_cancel


DENIED_PORTS = {8766, 8767, 8768, 18000, 18003, 18767, 18768, 18769, 18770, 8000, 8003}
MODELS = {"DeepSeek-V4-Flash", "deepseek-v4-flash", "deepseek-flash"}
MAX_SECONDS = 10.0


def verify_candidate_policy(gateway):
    """True来自既有免费政策且绑定当前身份；裸调用方布尔标记不够。"""
    from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
    settings, budget = gateway.settings, gateway.budget
    if not isinstance(budget, FreeCampusCalls) or not gateway._free_policy_verified or gateway._closed:
        raise ValueError('candidate_verified_free_gateway_required')
    proof = budget.proof
    required = {"version", "profile", "billing_mode", "personal_cost_micro_cny", "source", "confirmed_date",
                "endpoint_sha256", "request_model", "credential_sha256", "ledger_path"}
    url = urlsplit(settings.base_url)
    if (not isinstance(proof, dict) or set(proof) != required or proof['version'] != 1
            or proof['profile'] != 'campus' or proof['billing_mode'] != 'owner_confirmed_free'
            or type(proof['personal_cost_micro_cny']) is not int or proof['personal_cost_micro_cny'] != 0
            or proof['source'] != 'owner_confirmation' or proof['confirmed_date'] != '2026-10-19'
            or proof['endpoint_sha256'] != hashlib.sha256(settings.base_url.encode()).hexdigest()
            or proof['credential_sha256'] != hashlib.sha256(settings.api_key.encode()).hexdigest()
            or proof['request_model'] != settings.model or settings.model not in MODELS
            or budget.policy.model != settings.model or not settings.api_key
            or url.hostname == 'api.deepseek.com' or url.port in DENIED_PORTS):
        raise ValueError('candidate_free_policy_identity_mismatch')
    # 重开只校验同一个既有账本中的政策；不新建池、不处理旧unknown。
    reopened = FreeCampusCalls(budget.path, proof=proof)
    if reopened.identity != budget.identity:
        raise ValueError('candidate_free_policy_identity_mismatch')


def _payload(gateway, body):
    required = {'model', 'messages', 'max_tokens', 'stream', 'stream_options', 'n', 'tool_choice', 'thinking'}
    if (not isinstance(body, dict) or set(body) != required or body['model'] != gateway.settings.model
            or body['stream'] is not True or type(body['n']) is not int or body['n'] != 1
            or type(body['max_tokens']) is not int or not 1 <= body['max_tokens'] <= 256
            or body['stream_options'] != {'include_usage': True} or body['thinking'] != {'type': 'disabled'}
            or body['tool_choice'] != 'none'):
        raise ValueError('candidate_payload_invalid')
    messages = body['messages']
    if (not isinstance(messages, list) or not 2 <= len(messages) <= 129
            or any(not isinstance(row, dict) or set(row) != {'role', 'content'}
                   or not isinstance(row['role'], str) or row['role'] not in {'system', 'user', 'assistant'}
                   or not isinstance(row['content'], str) for row in messages)
            or messages[0]['role'] != 'system' or messages[-1]['role'] != 'user'
            or any(row['role'] == 'system' for row in messages[1:])
            or sum(len(row['content']) for row in messages) > 32000):
        raise ValueError('candidate_messages_invalid')
    try:
        return json.dumps(body, ensure_ascii=False).encode()
    except (ValueError, UnicodeError):
        raise ValueError('candidate_payload_invalid') from None


class CandidateResponse:
    """兼容AE的response.content接口，同时提供明确取消和自有任务退出ack。

    request_id只关联此句柄，不是正式话轮ID。创建对象不占用预算或联网。
    退出须等实际pump finally；调用方可有界等待wait_closed，不能提前退并发槽。
    """

    def __init__(self, gateway, body):
        verify_candidate_policy(gateway)
        self._gateway, self._payload = gateway, _payload(gateway, body)
        self._max_tokens = body['max_tokens']
        self.request_id = uuid4().hex
        self.status = None
        self.content = self._content()
        self._aid = self._upstream = self._close_task = None
        self._entered = self._locked = self._done = self._cancelled = False
        self._closed = asyncio.Event()
        self._usage = self._cache = self._first = self._started = None
        self._failure = None
        self._settled = False
        self._ledger_finalized = False
        self._loop = None
        self._timer = None

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError('candidate_event_loop_mismatch')
        self._loop = loop

    async def __aenter__(self):
        self._check_loop()
        if self._entered or self._closed.is_set():
            raise ValueError('candidate_handle_already_used')
        self._entered = True
        try:
            # 不用to_thread(lock.acquire)：取消排队的线程可能迟到取锁并永远不释放。
            while True:
                if self._cancelled or self._gateway._closed or self._closed.is_set():
                    raise ValueError('candidate_request_cancelled')
                if self._gateway._paid_lock.acquire(blocking=False):
                    break
                await asyncio.sleep(.005)
            self._locked = True
            if self._cancelled or self._closed.is_set():
                raise ValueError('candidate_request_cancelled')
            verify_candidate_policy(self._gateway)
            with self._gateway._connections_lock:
                if self._gateway._closed:
                    raise ValueError('candidate_gateway_closed')
                self._gateway._streams.add(self)
                self._gateway._candidate_handles[self.request_id] = self
            self._aid = self._gateway.budget.reserve('answer')
            self._started = perf_counter()
            self._timer = self._loop.call_later(MAX_SECONDS, self._expire)
            self._upstream = self._gateway._provider_transport.async_stream(self._payload)
            response = await self._upstream.__aenter__()
            if type(response.status) is not int or not 100 <= response.status <= 599:
                raise ValueError('candidate_status_invalid')
            self.status = response.status
            return self
        except BaseException as error:
            self._failure = 'client_disconnected' if isinstance(error, asyncio.CancelledError) else 'transport_error'
            await self.aclose()
            raise

    def _expire(self):
        self._failure = 'transport_error'
        task = asyncio.create_task(self.cancel())
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)

    def _usage_packet(self, usage):
        if not isinstance(usage, dict):
            raise ValueError('candidate_usage_invalid')
        values = [usage.get(key) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        if (any(type(value) is not int or value < 0 for value in values)
                or sum(values[:2]) != values[2] or values[1] > self._max_tokens):
            raise ValueError('candidate_usage_invalid')
        safe = dict(zip(('prompt_tokens', 'completion_tokens', 'total_tokens'), values))
        if self._usage is not None and self._usage != safe:
            raise ValueError('candidate_usage_changed')
        self._usage = safe
        self._cache = cache_evidence(usage, completed=False)
        return safe

    async def _content(self):
        parser, rows, total, event_size, finished = FinalContent(), [], 0, 0, False
        try:
            if self.status != 200:
                raise ValueError('candidate_provider_failed')
            async for line in self._upstream.content:
                if not isinstance(line, bytes) or len(line) > 65536:
                    raise ValueError('candidate_stream_invalid')
                total += len(line); event_size += len(line)
                if total > 524288 or event_size > 65536:
                    raise ValueError('candidate_stream_too_large')
                if line.strip():
                    rows.append(line)
                    continue
                data = b'\n'.join(row[5:].strip() for row in rows if row.startswith(b'data:'))
                rows, event_size = [], 0
                if not data:
                    continue
                if data == b'[DONE]':
                    parser.finish()
                    if not finished or self._usage is None:
                        raise ValueError('candidate_completion_invalid')
                    yield b'data: [DONE]\n'
                    self._done = True  # blank行交付后，消费者才能观察到完整DONE。
                    yield b'\n'
                    return
                packet = json.loads(data)
                if not isinstance(packet, dict) or packet.get('error') is not None:
                    raise ValueError('candidate_stream_invalid')
                output = {'choices': []}
                if packet.get('usage') is not None:
                    output['usage'] = self._usage_packet(packet['usage'])
                choices = packet.get('choices', [])
                if not isinstance(choices, list) or len(choices) > 1:
                    raise ValueError('candidate_choice_invalid')
                for choice in choices:
                    if (not isinstance(choice, dict) or type(choice.get('index', 0)) is not int
                            or choice.get('index', 0) != 0 or finished):
                        raise ValueError('candidate_choice_invalid')
                    delta = choice.get('delta', {})
                    if (not isinstance(delta, dict) or delta.get('tool_calls') or delta.get('function_call')
                            or delta.get('role', 'assistant') != 'assistant'):
                        raise ValueError('candidate_tool_or_delta_invalid')
                    projected = {}
                    if delta.get('content') is not None:
                        projected['content'] = parser.feed(delta['content'])
                        if projected['content'].strip() and self._first is None:
                            self._first = round((perf_counter()-self._started)*1000, 3)
                    reason = choice.get('finish_reason')
                    if reason is not None:
                        if reason != 'stop':
                            raise ValueError('candidate_finish_invalid')
                        parser.finish(); finished = True
                    output['choices'].append({'index': 0, 'delta': projected, 'finish_reason': reason})
                yield b'data: ' + json.dumps(output, ensure_ascii=False).encode() + b'\n'
                yield b'\n'
            raise ValueError('candidate_done_missing')
        except asyncio.CancelledError:
            self._failure = 'client_disconnected'
            raise
        except Exception:
            self._failure = 'stream_invalid'
            raise ValueError('candidate_stream_invalid') from None

    async def _close(self):
        # 不关闭整个pool。只有此句柄实际pump退出后才审计/退锁/发ack。
        if self._upstream is not None:
            await self._upstream.aclose()
            await self._upstream.wait_closed()
        if self._timer is not None:
            self._timer.cancel()
        failure = self._failure
        success = self.status == 200 and self._done and not self._cancelled and failure is None
        if not success and failure is None:
            failure = ('provider_http_error' if self.status not in {None, 200} else
                       'client_disconnected' if self._cancelled else 'missing_done')
        ledger_error = False
        if self._aid is not None:
            try:
                self._gateway.budget.finish(self._aid, self._usage if success else None, successful=success)
                self._ledger_finalized, self._settled = True, success
            except Exception:
                ledger_error, failure = True, 'transport_error'
            self._gateway._record_result(self._aid, status=self.status, failure=failure,
                done=success and not ledger_error, forwarded=False, usage_seen=self._usage is not None)
            evidence = dict(self._cache or cache_evidence(None, completed=False), completed=success and not ledger_error)
            self._gateway.responses.append({'attempt_id': self._aid, 'phase': 'answer', 'candidate': True,
                'stream': True, 'http_status': self.status, 'completed': success and not ledger_error,
                'usage': self._usage if success and not ledger_error else None, 'cache': evidence,
                'failure': failure, 'finish_reason': 'stop' if self._done else None,
                'model_ttft_ms': self._first,
                'provider_elapsed_ms': round((perf_counter()-self._started)*1000, 3)})
        else:
            self._ledger_finalized = True  # 尚未reserve，无上游调用或待结算预留。
        with self._gateway._connections_lock:
            self._gateway._streams.discard(self)
            self._gateway._candidate_handles.pop(self.request_id, None)
        self._payload = b''
        if self._locked:
            self._locked = False
            self._gateway._paid_lock.release()
        self._closed.set()
        if ledger_error:
            raise RuntimeError('candidate_ledger_close_unconfirmed') from None

    async def aclose(self):
        self._check_loop()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await finish_before_cancel(self._close_task)

    async def cancel(self):
        self._check_loop()
        self._cancelled = True
        await self.aclose()
        return await self.wait_closed()

    async def wait_closed(self):
        self._check_loop()
        await self._closed.wait()
        return {'request_id': self.request_id, 'owned_upstream_exited': True,
                'provider_compute_stopped': False, 'ledger_finalized': self._ledger_finalized,
                'usage_settled': self._settled}

    async def __aexit__(self, error_type, error, traceback):
        if error_type is not None and self._failure is None:
            self._failure = 'client_disconnected' if issubclass(error_type, asyncio.CancelledError) else 'stream_invalid'
        await self.aclose()
