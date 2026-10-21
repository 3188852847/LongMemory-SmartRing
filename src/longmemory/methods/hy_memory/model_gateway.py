"""自有回环模型网关：同一预算覆盖 Hy、旧提取、回答器；BGE 留在主环境。"""

from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import replace
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
from threading import Lock, Thread
from time import perf_counter
from urllib.parse import urlsplit

from longmemory.infrastructure.config.model_profiles import ModelProfileStore
from .budget import BudgetStopped
from .provider_transport import PersistentProviderTransport
from .answer_content import FinalStream, final_response
from .prefix_cache import cache_evidence, has_final_text
from .model_admission import ModelAdmission, AdmissionClosed, AdmissionFull, work_kind
from .observation import embedding_observation, detail_header, measured, observed_lock, span


MAX_BODY = 2_000_000
CHINESE_MEMORY_POLICY=("\n适配本地中文向量模型：记忆content、归纳和检索query使用简体中文，"
    "保留事实的否定、日期和不确定性。JSON字段名、工具名及工具调用规范保持原样；"
    "人名、地名等专名保留原文。不要把助手建议当作用户决定。")


def _verify_official_settings(settings):
    try:
        url = urlsplit(settings.base_url)
        if url.scheme != "https" or url.hostname != "api.deepseek.com" or url.port not in {None,443} or url.path.rstrip("/") not in {"","/v1"}:
            raise ValueError("selected_endpoint_price_unverified")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("selected_endpoint_price_unverified")
    except (TypeError, ValueError):
        raise ValueError("selected_endpoint_price_unverified") from None
    if not isinstance(settings.model, str) or settings.model not in {"deepseek-v4-flash","deepseek-flash"}:
        raise ValueError("selected_model_price_unverified")


def selected_model(root):
    store = ModelProfileStore(root)
    web, voice = store.selected("web"), store.selected("voice")
    if web != voice:
        raise ValueError("selected_web_voice_models_differ")
    settings = store.settings(web)
    url = urlsplit(settings.base_url)
    if web == "official":
        _verify_official_settings(settings)
    elif web != "campus" or url.scheme not in {"http", "https"} or (url.scheme == "http" and not settings.allow_http):
        raise ValueError("selected_profile_transport_unverified")
    identity = {"profile":web,"request_model":settings.model,
        "endpoint_sha256":hashlib.sha256(settings.base_url.encode()).hexdigest(),
        "credential_present":bool(settings.api_key)}
    if web == "campus":
        identity["billing_policy"] = "owner_confirmed_free"
    return settings, identity


def verify_cny_account(settings):
    """只返回币种和可用标记；余额数字不输出、不入报告。"""
    _verify_official_settings(settings)
    connection = http.client.HTTPSConnection("api.deepseek.com",timeout=settings.timeout_seconds)
    try:
        connection.request("GET","/user/balance",headers={"Authorization":"Bearer "+settings.api_key})
        response = connection.getresponse()
        data = response.read(MAX_BODY+1)
        if response.status != 200 or len(data)>MAX_BODY:
            raise ValueError("billing_currency_check_failed")
        body = json.loads(data)
        currencies = {row.get("currency") for row in body.get("balance_infos",[])}
        if currencies != {"CNY"} or body.get("is_available") is not True:
            raise ValueError("billing_currency_not_confirmed_cny")
        return {"currency":"CNY","available":True,"balance_amount_recorded":False}
    finally:
        connection.close()


class ModelGateway(AbstractContextManager):
    def __init__(self, *, settings, budget, encoder, currency_verified=False, free_policy_verified=False,
                 remote=None, remote_stream=None):
        from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
        free = isinstance(budget, FreeCampusCalls)
        if free and not free_policy_verified:
            raise ValueError("owner_free_policy_verification_required")
        if not free and not currency_verified:
            raise ValueError("billing_currency_required")
        if settings.model != budget.policy.model:
            raise ValueError("budget_provider_model_mismatch")
        if not free and (budget.policy.input_window_bound<2_097_152 or budget.policy.output_window_bound<524_288
                or budget.policy.input_micro_cny_per_token<2 or budget.policy.output_micro_cny_per_token<8):
            raise ValueError("budget_unproven_upper_bound")
        self.settings, self.budget, self.encoder = settings, budget, encoder
        self._free_policy_verified = free and free_policy_verified is True
        self.token = secrets.token_urlsafe(32)
        self._paid_lock, self._embedding_lock = Lock(), Lock()
        self._admission = ModelAdmission(self._paid_lock)
        self._provider_transport = PersistentProviderTransport(settings)
        self._remote = remote or self._send
        self._remote_stream = remote_stream or self._send_stream
        self._streams, self._connections_lock = set(), Lock()
        self._downstreams = set()
        self._candidate_handles = {}
        self._closed = False
        self.embedding_calls = 0
        self.embedding_inputs = 0
        self.responses = []
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            # 只限制自有回环客户端的阻塞读写，不改变上游模型30秒设置。
            timeout = 1.0
            def setup(self):
                super().setup()
                with gateway._connections_lock:
                    gateway._downstreams.add(self.connection)
            def handle(self):
                if not gateway._closed:
                    super().handle()
            def finish(self):
                try:
                    super().finish()
                finally:
                    with gateway._connections_lock:
                        gateway._downstreams.discard(self.connection)
            def log_message(self,*args): pass
            def do_GET(self):
                if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+gateway.token):
                    self.respond(401,{"error":"local_gateway_auth_failed"}); return
                if self.path == "/hy-background/v1/admission":
                    self.respond(200, gateway.background_readiness())
                else:
                    self.respond(404,{"error":"local_gateway_path_not_allowed"})
            def do_POST(self):
                self._hy_embedding_observation=None
                if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+gateway.token):
                    self.respond(401,{"error":"local_gateway_auth_failed"}); return
                paths = {f"/{phase}/v1/chat/completions":phase for phase in ("hy","baseline","answer","probe")}
                try:
                    size = int(self.headers.get("Content-Length","0"))
                    if not 0 < size <= MAX_BODY: raise ValueError("size")
                    body = json.loads(self.rfile.read(size))
                    if self.path == "/voice/v1/chat/completions" and body.get("stream") is True:
                        gateway.stream(body, self)
                    elif self.path == "/voice/v1/chat/completions":
                        status, payload = gateway.complete("answer", body)
                        self.respond(status, payload)
                    elif self.path == "/hy/v1/embeddings":
                        observation=embedding_observation(self.headers.get('X-Hy-Observation-Id'),
                            self.headers.get('X-Hy-Observe-Detail'))
                        self._hy_embedding_observation=observation
                        with observation.activate() if observation is not None else nullcontext():
                            result = gateway.embed(body,self.headers.get("X-Hy-Embedding-Role","document"))
                        self.respond(200,result)
                    elif self.path == "/hy-background/v1/chat/completions":
                        status, payload = gateway.complete("hy", body, work_class="background")
                        self.respond(status, payload)
                    elif self.path in paths:
                        status, payload = gateway.complete(paths[self.path],body)
                        self.respond(status,payload)
                    else: self.respond(404,{"error":"local_gateway_path_not_allowed"})
                except (AdmissionClosed, AdmissionFull):
                    self.respond(503,{"error":"model_admission_unavailable"})
                except BudgetStopped:
                    self.respond(429,{"error":"global_budget_stopped"})
                except Exception:
                    self.respond(400,{"error":"local_gateway_operation_failed"})
            def respond(self,status,body):
                payload=json.dumps(body,ensure_ascii=False).encode()
                self.send_response(status); self.send_header("Content-Type","application/json")
                observation=getattr(self,'_hy_embedding_observation',None)
                if observation is not None:
                    detail=detail_header(observation)
                    if detail:
                        self.send_header('X-Hy-Observation-Detail',detail)
                self.send_header("Content-Length",str(len(payload))); self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.server.daemon_threads = False
        if self.server.server_port in {8766,8767,8768,8000,8003,18767,18768,18769,18770}:
            self.server.server_close(); raise ValueError("gateway_daily_port_rejected")
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever,daemon=True)

    def __enter__(self):
        self.thread.start(); return self

    def __exit__(self,*args):
        self.close()

    def close(self):
        with self._connections_lock:
            if self._closed:
                return
            self._closed = True
            downstreams = tuple(self._downstreams)
        self._admission.close()
        # 不持登记锁执行取消/shutdown或join：处理线程finally也需取此锁。
        transport_failure = None
        try:
            self._provider_transport.close()
        except RuntimeError as error:
            transport_failure = error
        for connection in downstreams:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
        if transport_failure is not None:
            raise transport_failure

    def local_settings(self, phase, *, max_tokens=1024, work_class=None):
        from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
        kind = work_kind(phase, work_class)
        route = "hy-background" if kind == "background" else phase
        return replace(self.settings,base_url=self.base+f"/{route}/v1",api_key=self.token,
            allow_http=True,max_tokens=max_tokens,timeout_seconds=(self.settings.timeout_seconds
                if isinstance(self.budget, FreeCampusCalls) else max(60,self.settings.timeout_seconds*2)))

    def background_readiness(self):
        """仅建议，不返回lease或预留；AB应在任务running/SDK原子操作之前查询。"""
        return self._admission.background_readiness()

    @measured('embed_gateway_ms')
    def embed(self,body,role):
        if body.get("model") != self.encoder.identity or role not in {"query","document"}:
            raise ValueError("embedding_identity_or_role_invalid")
        texts = body.get("input")
        if isinstance(texts,str):texts=[texts]
        if not isinstance(texts,list) or not 1 <= len(texts) <= 128 or any(not isinstance(text,str) or not text.strip() for text in texts):
            raise ValueError("embedding_input_invalid")
        with observed_lock(self._embedding_lock,'embed_gateway_lock_wait_ms'):
            with span('embed_bge_encode_ms'):
                vectors = ([self.encoder.encode_query(text) for text in texts] if role == "query"
                           else self.encoder.encode_documents(texts))
            self.embedding_calls+=1; self.embedding_inputs+=len(texts)
        return {"object":"list","model":self.encoder.identity,
            "data":[{"object":"embedding","index":i,"embedding":vector} for i,vector in enumerate(vectors)]}

    def complete(self,phase,body,*,work_class=None):
        kind = work_kind(phase, work_class)
        if not isinstance(body,dict) or body.get("model") != self.settings.model or body.get("stream",False) is not False:
            raise ValueError("model_payload_invalid")
        # 禁止服务器搜索/抓取等另收费工具；SDK 只可声明本地 function 工具。
        if any(not isinstance(tool,dict) or tool.get("type") != "function" for tool in body.get("tools",[])):
            raise ValueError("server_tool_not_allowed")
        if type(body.get("max_tokens")) is not int or not 1 <= body["max_tokens"] <= 8192:
            raise ValueError("output_limit_required")
        body=dict(body)
        if phase=="hy":
            messages=[dict(message) for message in body.get("messages",[])]
            system=next((message for message in messages if message.get("role")=="system" and isinstance(message.get("content"),str)),None)
            if system is None:raise ValueError("hy_system_prompt_required")
            system["content"]+=CHINESE_MEMORY_POLICY
            body["messages"]=messages
        body["thinking"]={"type":"disabled"}
        # 独立核实 API 全窗口上界来预留；不拿下面的 body 字节数估 token。
        payload=json.dumps(body,ensure_ascii=False).encode()
        if len(payload)>MAX_BODY:raise ValueError("model_payload_too_large")
        with self._admission.acquire(kind) as admission:
            if self._closed:
                raise BudgetStopped("gateway_closed")
            aid=self.budget.reserve(phase)
            status, usage, failure = None, None, None
            started = perf_counter()
            try:
                status,data=self._remote(payload)
                parsed=json.loads(data)
                usage=parsed.get("usage") if isinstance(parsed,dict) else None
                if status == 200 and phase in {"answer", "probe"}:
                    parsed = final_response(parsed)
                self.budget.finish(aid,usage,successful=status==200)
                self.responses.append({"attempt_id":aid,"phase":phase,"http_status":status,
                    "response_model":parsed.get("model") if isinstance(parsed,dict) else None,
                    "usage":usage,"finish_reason":((parsed.get("choices") or [{}])[0].get("finish_reason") if isinstance(parsed,dict) else None),
                    "cache":cache_evidence(usage, completed=status==200),
                    **admission.metadata(),
                    # 非流式只能测完整响应时间，不能把它冒充TTFT。
                    "model_ttft_ms":None, "provider_elapsed_ms":round((perf_counter()-started)*1000, 3)})
                if status!=200:
                    failure = "provider_http_error"
                    return 502,{"error":"selected_provider_failed"}
                return status,parsed
            except Exception:
                failure = "transport_error"
                # 如果已结算再发生本地处理错误，保留该结算；未结算保持整次最坏预留。
                try:self.budget.finish(aid,None,successful=False)
                except BudgetStopped:pass
                return 502,{"error":"selected_provider_transport_failed"}
            finally:
                self._record_result(aid, status=status, failure=failure, done=status==200 and failure is None,
                    forwarded=False, usage_seen=usage is not None)

    def _send(self, payload):
        return self._provider_transport.send(payload)

    def candidate_response_binding(self):
        """导出同一策略/账本/连接池的候选接口，不创建新的网关或消费配置。"""
        from .candidate_response import verify_candidate_policy
        verify_candidate_policy(self)
        return {"open_response": self.open_candidate_response, "model": self.settings.model,
                "campus_free_verified": True}

    def open_candidate_response(self, body):
        from .candidate_response import CandidateResponse
        return CandidateResponse(self, body)

    async def cancel_candidate(self, request_id):
        """句柄只索引候选；不得通过正式回答的attempt_id取消正式请求。"""
        with self._connections_lock:
            handle = self._candidate_handles.get(request_id)
        if handle is None:
            raise ValueError('candidate_handle_not_active')
        return await handle.cancel()

    def _record_result(self, aid, **metadata):
        try:
            self.budget.record_gateway_result(aid, **metadata)
        except Exception:
            # 诊断写失败不能改写已结算费用，也不能放弃原来的unknown预留。
            pass

    @contextmanager
    def _send_stream(self, payload):
        # 会话和连接池属于本次网关身份。只登记实际请求，既不预请求也不缓存答案。
        # 保留活跃标记供生命周期/IP维护门判定；关闭由持久传输取消全部任务。
        marker = object()
        with self._connections_lock:
            if self._closed:
                raise ValueError('gateway_closed')
            self._streams.add(marker)
        try:
            with self._provider_transport.stream(payload) as response:
                yield response
        finally:
            with self._connections_lock:
                self._streams.discard(marker)

    def stream(self, body, handler):
        """按SSE事件投影最终答案；最终usage和DONE均成功转发才释放最坏预留。

        取消、缺usage、断流或本地写失败保留unknown；不缓存整回答再伪分块。
        供应商密钥、原始错误和消息正文不进入预算/诊断。
        """
        if (not isinstance(body, dict) or body.get("model") != self.settings.model
                or body.get("stream") is not True or type(body.get("max_tokens")) is not int
                or not 1 <= body["max_tokens"] <= 8192
                or any(not isinstance(tool, dict) or tool.get("type") != "function" for tool in (body.get("tools") or []))):
            raise ValueError("voice_stream_payload_invalid")
        body = dict(body, thinking={"type": "disabled"}, stream_options={"include_usage": True})
        payload = json.dumps(body, ensure_ascii=False).encode()
        if len(payload) > MAX_BODY:
            raise ValueError("model_payload_too_large")
        with self._admission.acquire("answer") as admission:
            if self._closed:
                raise BudgetStopped("gateway_closed")
            aid = self.budget.reserve("answer")
            started, first_text = perf_counter(), None
            usage, done, total, event_lines, event_size = None, False, 0, [], 0
            final_content = FinalStream()
            finish_reason = None
            status, failure, writing, forwarded = None, None, False, False
            try:
                with self._remote_stream(payload) as (status, lines):
                    if status != 200:
                        failure = "provider_http_error"
                        handler.respond(502, {"error": "selected_provider_failed"})
                    else:
                        handler.send_response(200)
                        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        handler.send_header("Cache-Control", "no-store")
                        handler.send_header("Connection", "close")
                        handler.end_headers()
                        handler.close_connection = True
                        for line in lines:
                            if self._closed or not isinstance(line, bytes) or len(line) > 131072:
                                raise ValueError("provider_stream_interrupted")
                            total += len(line)
                            if total > 32 * MAX_BODY:
                                raise ValueError("provider_stream_too_large")
                            event_lines.append(line)
                            event_size += len(line)
                            if event_size > MAX_BODY:
                                raise ValueError("provider_stream_event_too_large")
                            if line.strip():
                                continue
                            data = b"\n".join(row[5:].strip() for row in event_lines if row.startswith(b"data:"))
                            event_lines.clear()
                            event_size = 0
                            if data == b"[DONE]":
                                final_content.finish()
                                writing = True
                                handler.wfile.write(b"data: [DONE]\n\n")
                                handler.wfile.flush()
                                writing, forwarded = False, True
                                done = True
                                break
                            if data:
                                packet = json.loads(data)
                                if not isinstance(packet, dict):
                                    raise ValueError("provider_stream_invalid")
                                if packet.get("usage") is not None:
                                    usage = packet["usage"]
                                packet = final_content.packet(packet)
                                for choice in packet.get("choices") or []:
                                    reason = choice.get("finish_reason")
                                    if reason is not None:
                                        finish_reason = reason if isinstance(reason, str) and reason in {"stop", "length", "tool_calls", "content_filter", "function_call"} else "other"
                                if first_text is None and has_final_text(packet, streaming=True):
                                    first_text = round((perf_counter()-started)*1000, 3)
                                writing = True
                                handler.wfile.write(b"data: " + json.dumps(packet, ensure_ascii=False).encode() + b"\n\n")
                                handler.wfile.flush()
                                writing, forwarded = False, True
                if self._closed:
                    failure = "gateway_closed"
                elif status == 200 and not done:
                    failure = "missing_done"
                elif done and usage is None:
                    failure = "missing_usage"
                self.budget.finish(aid, usage, successful=done)
            except Exception as error:
                failure = ("gateway_closed" if self._closed else "client_disconnected" if writing
                    else "stream_invalid" if isinstance(error, (ValueError, TypeError)) else "transport_error")
                self.budget.finish(aid, None, successful=False)
                # 已发SSE头后只终止连接，不追加JSON或伪造DONE，调用者不得自动重试。
                handler.close_connection = True
            self._record_result(aid, status=status, failure=failure, done=done,
                forwarded=forwarded, usage_seen=usage is not None)
            self.responses.append({"attempt_id": aid, "phase": "answer", "stream": True,
                "completed": done, "usage": usage if done else None, "failure": failure, "http_status": status,
                "cache":cache_evidence(usage, completed=done and failure is None),
                **admission.metadata(),
                "finish_reason":finish_reason,
                "model_ttft_ms":first_text, "provider_elapsed_ms":round((perf_counter()-started)*1000, 3)})
