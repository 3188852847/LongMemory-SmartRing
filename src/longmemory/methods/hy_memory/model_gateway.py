"""自有回环模型网关：同一预算覆盖 Hy、旧提取、回答器；BGE 留在主环境。"""

from contextlib import AbstractContextManager, contextmanager
import asyncio
from concurrent.futures import Future
from dataclasses import replace
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
from queue import Queue
from threading import Lock, Thread
from urllib.parse import urlsplit

from longmemory.infrastructure.config.model_profiles import ModelProfileStore
from .budget import BudgetStopped


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
        self.token = secrets.token_urlsafe(32)
        self._paid_lock, self._embedding_lock = Lock(), Lock()
        self._remote = remote or self._send
        self._remote_stream = remote_stream or self._send_stream
        self._streams, self._connections_lock = set(), Lock()
        self._downstreams = set()
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
            def do_POST(self):
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
                        result = gateway.embed(body,self.headers.get("X-Hy-Embedding-Role","document"))
                        self.respond(200,result)
                    elif self.path in paths:
                        status, payload = gateway.complete(paths[self.path],body)
                        self.respond(status,payload)
                    else: self.respond(404,{"error":"local_gateway_path_not_allowed"})
                except BudgetStopped:
                    self.respond(429,{"error":"global_budget_stopped"})
                except Exception:
                    self.respond(400,{"error":"local_gateway_operation_failed"})
            def respond(self,status,body):
                payload=json.dumps(body,ensure_ascii=False).encode()
                self.send_response(status); self.send_header("Content-Type","application/json")
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
            streams, downstreams = tuple(self._streams), tuple(self._downstreams)
        # 不持登记锁执行取消/shutdown或join：处理线程finally也需取此锁。
        for loop, task in streams:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
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

    def local_settings(self, phase, *, max_tokens=1024):
        from longmemory.infrastructure.config.campus_calls import FreeCampusCalls
        return replace(self.settings,base_url=self.base+f"/{phase}/v1",api_key=self.token,
            allow_http=True,max_tokens=max_tokens,timeout_seconds=(self.settings.timeout_seconds
                if isinstance(self.budget, FreeCampusCalls) else max(60,self.settings.timeout_seconds*2)))

    def embed(self,body,role):
        if body.get("model") != self.encoder.identity or role not in {"query","document"}:
            raise ValueError("embedding_identity_or_role_invalid")
        texts = body.get("input")
        if isinstance(texts,str):texts=[texts]
        if not isinstance(texts,list) or not 1 <= len(texts) <= 128 or any(not isinstance(text,str) or not text.strip() for text in texts):
            raise ValueError("embedding_input_invalid")
        with self._embedding_lock:
            vectors = ([self.encoder.encode_query(text) for text in texts] if role == "query"
                       else self.encoder.encode_documents(texts))
            self.embedding_calls+=1; self.embedding_inputs+=len(texts)
        return {"object":"list","model":self.encoder.identity,
            "data":[{"object":"embedding","index":i,"embedding":vector} for i,vector in enumerate(vectors)]}

    def complete(self,phase,body):
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
        with self._paid_lock:
            if self._closed:
                raise BudgetStopped("gateway_closed")
            aid=self.budget.reserve(phase)
            status, usage, failure = None, None, None
            try:
                status,data=self._remote(payload)
                parsed=json.loads(data)
                usage=parsed.get("usage") if isinstance(parsed,dict) else None
                self.budget.finish(aid,usage,successful=status==200)
                self.responses.append({"attempt_id":aid,"phase":phase,"http_status":status,
                    "response_model":parsed.get("model") if isinstance(parsed,dict) else None,
                    "usage":usage,"finish_reason":((parsed.get("choices") or [{}])[0].get("finish_reason") if isinstance(parsed,dict) else None)})
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

    def _send(self,payload):
        url=urlsplit(self.settings.base_url)
        connection=self._provider_connection(url)
        try:
            connection.request("POST",url.path.rstrip("/")+"/chat/completions",body=payload,
                headers={"Content-Type":"application/json","Authorization":"Bearer "+self.settings.api_key})
            response=connection.getresponse()
            data=response.read(MAX_BODY+1)
            if len(data)>MAX_BODY:raise ValueError("provider_response_too_large")
            return response.status,data
        finally:connection.close()

    def _provider_connection(self, url):
        if url.scheme == "https":
            return http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=self.settings.timeout_seconds)
        if url.scheme == "http" and self.settings.allow_http:
            return http.client.HTTPConnection(url.hostname, url.port or 80, timeout=self.settings.timeout_seconds)
        raise ValueError("provider_transport_not_authorized")

    def _record_result(self, aid, **metadata):
        try:
            self.budget.record_gateway_result(aid, **metadata)
        except Exception:
            # 诊断写失败不能改写已结算费用，也不能放弃原来的unknown预留。
            pass

    @contextmanager
    def _send_stream(self, payload):
        import aiohttp
        url = urlsplit(self.settings.base_url)
        if url.scheme not in {"http", "https"} or (url.scheme == "http" and not self.settings.allow_http):
            raise ValueError("provider_transport_not_authorized")
        # 只替换上游流传输。异步取消不依赖另一个线程关闭正在readline的
        # BufferedReader；不先缓存完整回答，不重试，也不跟随重定向。
        loop, packets, headers, end = asyncio.new_event_loop(), Queue(), Future(), object()
        async def pump():
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.settings.timeout_seconds,
                sock_read=self.settings.timeout_seconds)
            try:
                async with aiohttp.ClientSession(timeout=timeout, cookie_jar=aiohttp.DummyCookieJar(),
                        read_bufsize=131072) as session:
                    async with session.post(self.settings.base_url.rstrip("/")+"/chat/completions",
                            data=payload, allow_redirects=False,
                            headers={"Content-Type":"application/json","Authorization":"Bearer "+self.settings.api_key}) as response:
                        headers.set_result(response.status)
                        total = 0
                        async for line in response.content:
                            total += len(line)
                            if len(line) > 131072 or total > 32*MAX_BODY:
                                raise ValueError("provider_stream_too_large")
                            packets.put(line)
            except BaseException as error:
                safe = ValueError("provider_stream_invalid") if isinstance(error, ValueError) else OSError("provider_stream_interrupted")
                if not headers.done():
                    headers.set_exception(safe)
                packets.put(safe)
            finally:
                packets.put(end)
        task = loop.create_task(pump())
        def run():
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(task)
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
        thread = Thread(target=run, name="hy-provider-stream")
        with self._connections_lock:
            if self._closed:
                task.cancel()
                loop.run_until_complete(asyncio.gather(task, return_exceptions=True));loop.close()
                raise ValueError("gateway_closed")
            self._streams.add((loop, task))
            thread.start()
        try:
            def lines():
                while True:
                    line = packets.get()
                    if line is end:
                        break
                    if isinstance(line, Exception):
                        raise line
                    yield line
            yield headers.result(timeout=self.settings.timeout_seconds+1), lines()
        finally:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
            thread.join(timeout=5)
            with self._connections_lock:
                self._streams.discard((loop, task))
            if thread.is_alive():
                raise RuntimeError("provider_stream_close_unconfirmed")

    def stream(self, body, handler):
        """边收边转发真实SSE；最终usage和DONE均成功转发才释放最坏预留。

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
        with self._paid_lock:
            if self._closed:
                raise BudgetStopped("gateway_closed")
            aid = self.budget.reserve("answer")
            usage, done, total, event_lines = None, False, 0, []
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
                            writing = True
                            handler.wfile.write(line)
                            handler.wfile.flush()
                            writing, forwarded = False, True
                            if line.strip():
                                continue
                            data = b"\n".join(row[5:].strip() for row in event_lines if row.startswith(b"data:"))
                            event_lines.clear()
                            if data == b"[DONE]":
                                done = True
                                break
                            if data:
                                packet = json.loads(data)
                                if not isinstance(packet, dict):
                                    raise ValueError("provider_stream_invalid")
                                if packet.get("usage") is not None:
                                    usage = packet["usage"]
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
                "completed": done, "usage": usage if done else None, "failure": failure, "http_status": status})
