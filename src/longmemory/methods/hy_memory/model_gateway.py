"""自有回环模型网关：同一预算覆盖 Hy、旧提取、回答器；BGE 留在主环境。"""

from contextlib import AbstractContextManager
from dataclasses import replace
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from threading import Lock, Thread
from urllib.parse import urlsplit

from longmemory.infrastructure.config.model_profiles import ModelProfileStore
from .budget import BudgetStopped


MAX_BODY = 2_000_000


def selected_model(root):
    store = ModelProfileStore(root)
    web, voice = store.selected("web"), store.selected("voice")
    if web != voice:
        raise ValueError("selected_web_voice_models_differ")
    settings = store.settings(web)
    url = urlsplit(settings.base_url)
    if url.scheme != "https" or url.hostname != "api.deepseek.com" or url.port not in {None,443} or url.path.rstrip("/") not in {"","/v1"}:
        raise ValueError("selected_endpoint_price_unverified")
    if settings.model not in {"deepseek-v4-flash","deepseek-flash"}:
        raise ValueError("selected_model_price_unverified")
    return settings, {"profile":web,"request_model":settings.model,
        "endpoint_sha256":hashlib.sha256(settings.base_url.encode()).hexdigest(),
        "credential_present":bool(settings.api_key)}


def verify_cny_account(settings):
    """只返回币种和可用标记；余额数字不输出、不入报告。"""
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
    def __init__(self, *, settings, budget, encoder, currency_verified=False, remote=None):
        if not currency_verified:
            raise ValueError("billing_currency_required")
        if settings.model != budget.policy.model:
            raise ValueError("budget_provider_model_mismatch")
        if (budget.policy.input_window_bound<2_097_152 or budget.policy.output_window_bound<524_288
                or budget.policy.input_micro_cny_per_token<2 or budget.policy.output_micro_cny_per_token<8):
            raise ValueError("budget_unproven_upper_bound")
        self.settings, self.budget, self.encoder = settings, budget, encoder
        self.token = secrets.token_urlsafe(32)
        self._paid_lock, self._embedding_lock = Lock(), Lock()
        self._remote = remote or self._send
        self.embedding_calls = 0
        self.embedding_inputs = 0
        self.responses = []
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                if not hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+gateway.token):
                    self.respond(401,{"error":"local_gateway_auth_failed"}); return
                paths = {f"/{phase}/v1/chat/completions":phase for phase in ("hy","baseline","answer","probe")}
                try:
                    size = int(self.headers.get("Content-Length","0"))
                    if not 0 < size <= MAX_BODY: raise ValueError("size")
                    body = json.loads(self.rfile.read(size))
                    if self.path == "/hy/v1/embeddings":
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
        if self.server.server_port in {8767,8000,8003}:
            self.server.server_close(); raise ValueError("gateway_daily_port_rejected")
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever,daemon=True)

    def __enter__(self):
        self.thread.start(); return self

    def __exit__(self,*args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)

    def local_settings(self, phase, *, max_tokens=1024):
        return replace(self.settings,base_url=self.base+f"/{phase}/v1",api_key=self.token,
            allow_http=True,max_tokens=max_tokens,timeout_seconds=max(60,self.settings.timeout_seconds*2))

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
        body["thinking"]={"type":"disabled"}
        # 独立核实 API 全窗口上界来预留；不拿下面的 body 字节数估 token。
        payload=json.dumps(body,ensure_ascii=False).encode()
        if len(payload)>MAX_BODY:raise ValueError("model_payload_too_large")
        with self._paid_lock:
            aid=self.budget.reserve(phase)
            try:
                status,data=self._remote(payload)
                parsed=json.loads(data)
                usage=parsed.get("usage") if isinstance(parsed,dict) else None
                self.budget.finish(aid,usage,successful=status==200)
                self.responses.append({"attempt_id":aid,"phase":phase,"http_status":status,
                    "response_model":parsed.get("model") if isinstance(parsed,dict) else None,
                    "usage":usage,"finish_reason":((parsed.get("choices") or [{}])[0].get("finish_reason") if isinstance(parsed,dict) else None)})
                if status!=200:return 502,{"error":"selected_provider_failed"}
                return status,parsed
            except Exception:
                # 如果已结算再发生本地处理错误，保留该结算；未结算保持整次最坏预留。
                try:self.budget.finish(aid,None,successful=False)
                except BudgetStopped:pass
                return 502,{"error":"selected_provider_transport_failed"}

    def _send(self,payload):
        url=urlsplit(self.settings.base_url)
        connection=http.client.HTTPSConnection(url.hostname,443,timeout=self.settings.timeout_seconds)
        try:
            connection.request("POST",url.path.rstrip("/")+"/chat/completions",body=payload,
                headers={"Content-Type":"application/json","Authorization":"Bearer "+self.settings.api_key})
            response=connection.getresponse()
            data=response.read(MAX_BODY+1)
            if len(data)>MAX_BODY:raise ValueError("provider_response_too_large")
            return response.status,data
        finally:connection.close()
