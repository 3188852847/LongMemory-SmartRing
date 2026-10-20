"""仅供独立解释器启动的 SDK worker；stdout 只写协议，不回传 SDK 错误正文。"""

from contextlib import redirect_stdout, redirect_stderr, nullcontext
from datetime import datetime
from importlib import metadata
import json
import os
import platform
from pathlib import Path
import socket
import sys
from threading import Lock, local
from urllib.parse import urlsplit

from .process_client import MAX_LINE
from .sdk_bridge import SDK_VERSION
from .settings import HySettings
from .source_evidence import enrich_profile,enrich_search
from .management_rpc import ManagementRPC, profile_scope_proof
from .sdk_bridge import SOURCE_NAMESPACE
from .observation import Observation, span


class RequestBudget:
    """单 worker 生命周期上限；不是多个题目副本/进程共享的整轮预算。"""
    def __init__(self, settings):
        self.settings = settings
        self.attempts = 0
        self.simulated_requests = 0
        self.local_gateway_requests = 0
        self.management_embedding_attempts = 0
        self.management_llm_attempts_blocked = 0
        self._lock = Lock()

    def check_management_request(self, url):
        if getattr(self,"operation",None) not in {"update","delete"}:
            return
        with self._lock:
            if self.operation != "update" or not str(url).rstrip("/").endswith("/embeddings"):
                self.management_llm_attempts_blocked += 1
                raise RuntimeError("hy_management_llm_denied")
            self.management_embedding_attempts += 1

    def claim(self, url):
        endpoints = (self.settings.llm.base_url.rstrip("/") + "/", self.settings.embedding.base_url.rstrip("/") + "/")
        with self._lock:
            if not self.settings.network_authorized or not any(str(url).startswith(base) for base in endpoints):
                raise RuntimeError("hy_network_denied")
            if self.attempts >= self.settings.max_external_requests:
                raise RuntimeError("hy_request_budget_exhausted")
            self.attempts += 1
            if urlsplit(str(url)).scheme == "http":self.local_gateway_requests += 1

    def report(self):
        return {"external_http_attempts": self.attempts-self.local_gateway_requests, "local_gateway_requests":self.local_gateway_requests,"external_tokens": None, "cost": None,
                "short_embedding_input": self.short_embedding_input.snapshot() if hasattr(self,'short_embedding_input') else None,
                "sdk_observation_applied": bool(getattr(getattr(self,'sdk_observation',None),'applied',False)),
                "local_initialization": getattr(self,'local_initialization',None),
                "simulated_model_requests":self.simulated_requests, "model_mode":self.settings.model_mode,
                "input_token_estimator":"sdk_character_fallback_no_bpe_download",
                "actual_sdk_version":getattr(self,"actual_sdk_version",None),
                "sdk_python":getattr(self,"sdk_python",None),
                "management_embedding_attempts":self.management_embedding_attempts,
                "management_llm_attempts_blocked":self.management_llm_attempts_blocked,
                "hard_limit": {"external_requests": self.settings.max_external_requests},
                "token_and_currency_limits_enforced": False}


def install_network_denial(allowed_addresses=()):
    """保留 Windows asyncio 必需的 stdlib socketpair，仅放行其内部回环自连接。"""
    pair_context = local()
    connect, connect_ex, pair, resolve = socket.socket.connect, socket.socket.connect_ex, socket.socketpair, socket.getaddrinfo
    allowed_addresses=set(allowed_addresses)
    def guarded(original):
        def run(sock, address):
            if getattr(pair_context, "active", False) and isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
                return original(sock, address)
            if isinstance(address,tuple) and address[:2] in allowed_addresses:
                return original(sock,address)
            raise OSError("hy_network_disabled")
        return run
    def local_pair(*args, **kwargs):
        pair_context.active = True
        try:
            return pair(*args, **kwargs)
        finally:
            pair_context.active = False
    def deny(*args, **kwargs):
        raise OSError("hy_network_disabled")
    def local_resolve(host,port,*args,**kwargs):
        if (host,port) in allowed_addresses:return resolve(host,port,*args,**kwargs)
        raise OSError("hy_network_disabled")
    socket.socketpair = local_pair
    socket.socket.connect = guarded(connect)
    socket.socket.connect_ex = guarded(connect_ex)
    socket.socket.sendto = deny
    socket.getaddrinfo = local_resolve


def create_sdk(settings, workspace, *, create, short_embedding_fast_path=True, prepare_local_backends=True):
    if metadata.version("hy-memory") != SDK_VERSION:
        raise ValueError("hy_sdk_version_mismatch")
    # 默认在 socket 层拒绝网络，包含库初始化的遥测/意外网络路径。
    if not settings.network_authorized:
        install_network_denial()
    elif settings.managed_gateway:
        install_network_denial([(urlsplit(endpoint.base_url).hostname,urlsplit(endpoint.base_url).port) for endpoint in (settings.llm,settings.embedding)])
    else:
        raise ValueError("hy_real_requests_require_shared_budget_gateway")
    os.environ["MEMORY_DATA_DIR"] = str(workspace)
    sdk = workspace / "sdk"
    fresh = not any(path.is_file() for path in sdk.rglob("*"))
    if not create and not (sdk / "vector/chroma.sqlite3").is_file():
        raise FileNotFoundError("hy_existing_vector_store_missing")
    import httpx
    from hy_memory import HyMemoryClient, MemoryConfig
    # SDK 自带 len//4 回退；预置不可用标记，避免 token 估算器隐式下载 BPE 文件。
    # 不是供应商 token 用量，不用于收费推断。
    from hy_memory.utils import token_count
    token_count._encoder = False
    budget = RequestBudget(settings)
    from hy_memory.core import embed_service
    from .short_embedding_input import ShortEmbeddingInput
    budget.short_embedding_input = ShortEmbeddingInput(embed_service,
        sdk_version=SDK_VERSION, enabled=short_embedding_fast_path)
    budget.management_workspace = workspace
    budget.actual_sdk_version = metadata.version("hy-memory")
    budget.sdk_python = platform.python_version()

    def synthetic_response(request):
        budget.check_management_request(request.url)
        with budget._lock:
            budget.simulated_requests += 1
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            return httpx.Response(200, json={"data":[{"object":"embedding", "index":i,
                "embedding":[1.0] + [0.0] * (settings.embedding_dimensions-1)} for i in range(len(inputs))]})
        if request.url.path.endswith("/chat/completions"):
            # 固定一条测试事实；与历史/题目无关，不能用于质量比较。
            content = json.dumps({"memory":[{"content":"合成用户喜欢无糖乌龙茶", "tags":["synthetic"], "owner":"user"}], "intentions":[], "basic_info":{}}, ensure_ascii=False)
            return httpx.Response(200, json={"id":"synthetic-completion", "object":"chat.completion",
                "model":"synthetic-offline", "choices":[{"index":0,"finish_reason":"stop",
                "message":{"role":"assistant","content":content}}]})
        raise RuntimeError("hy_mock_endpoint_unknown")

    class BoundedTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(retries=0)

        async def handle_async_request(self, request):
            budget.check_management_request(request.url)
            budget.claim(request.url)
            if request.url.path.endswith("/embeddings"):
                # search RPC 的查询用 BGE 查询前缀；add 内部 reconcile 的查询无法
                # 从标准 Embedding API 区分，仍按 document，实验明确记录该差异。
                request.headers["X-Hy-Embedding-Role"] = "query" if getattr(budget,"operation",None)=="search" else "document"
            response = await self.inner.handle_async_request(request)
            # 重定向不发给未经配置的端点；SDK 内部 retry 也受统一计数上限约束。
            if 300 <= response.status_code < 400:
                await response.aclose()
                raise RuntimeError("hy_redirect_denied")
            return response

        async def aclose(self):
            await self.inner.aclose()

    def endpoint(value):
        return {"provider":"openai", "base_url":value.base_url, "api_key":value.api_key,
                "model":value.model, "timeout":settings.timeout_seconds, "max_retries":0}
    config = MemoryConfig.from_dict({
        "vector_store":{"provider":"chroma", "persist_directory":str(sdk / "vector"),
                        "embedding_dims":settings.embedding_dimensions, "collection_name":"smartring_synthetic"},
        "graph_store":{"db_path":str(sdk / "graph")},
        "cache":{"backend":"sqlite", "db_path":str(sdk / "cache.db"),
                 "enable_profile_cache":False, "enable_system2_queue":False, "enable_intention_cache":False},
        "history":{"enable":False, "db_path":str(sdk / "history.db"), "record_searches":False},
        "coding":{"enable":False, "db_path":str(sdk / "coding.db")},
        # 2.0.3 LLM 的 max_retries 实际是总尝试次数，1 才是单次、无重试。
        "llm":{**endpoint(settings.llm), "max_retries":1, "max_tokens":settings.max_output_tokens,
               "agent_max_tokens":settings.max_output_tokens, "enable_query_rewrite":False, "enable_intention":False},
        "embedder":{**endpoint(settings.embedding), "embedding_dims":settings.embedding_dimensions},
        "recall":{"strength_enabled":False, "access_tracking_enabled":False,
                  "retrieval_clauses_enabled":False},
        "enable_graph":False, "metrics_enabled":False, "debug":False,
    })
    config.http_transport_factory = (lambda: httpx.MockTransport(synthetic_response)) if settings.model_mode == "synthetic_transport" else BoundedTransport
    client = HyMemoryClient(config=config, mode="pro")
    from .sdk_observation import SDKObservation
    budget.sdk_observation=SDKObservation(sdk_version=SDK_VERSION)
    budget.local_initialization = (budget.sdk_observation.prepare_local_backends()
        if prepare_local_backends else {'prepared': False, 'import_ms': 0.0, 'segmenter_ms': 0.0})
    # 只给已核实的 2.0.3 本地 Chroma 配置声明 update；其他 factory 默认不具备。
    budget.management_update_verified = (type(client._vector_store).__name__ == "ChromaVectorStore"
        and not client._graph_store and not config.enable_graph and not config.coding.enable
        and config.recall.retrieval_clauses_enabled is False
        and getattr(client._vector_store,"_supports_retrieval_clauses",True) is False
        and getattr(client._vector_store,"_supports_tag_index",True) is False)
    try:
        budget.management_profile_scope_proven = profile_scope_proof(workspace,settings,
            create=create,fresh=fresh,verified=budget.management_update_verified)
    except BaseException:
        client.close()
        raise
    return client, budget


class ProtocolService:
    def __init__(self, factory=create_sdk):
        self.factory = factory
        self.client = self.budget = None
        self.settings = self.management = None

    def execute(self, operation, arguments):
        if operation == "initialize":
            if self.client is not None:
                raise ValueError("hy_worker_already_initialized")
            self.settings = HySettings.from_wire(arguments["settings"])
            self.client, self.budget = self.factory(self.settings,
                Path(arguments["workspace"]), create=arguments["create"])
            self.management = ManagementRPC(self.client,self.settings,self.budget)
            return {"ready":True, "sdk_version":SDK_VERSION}
        if self.client is None:
            raise ValueError("hy_worker_not_initialized")
        if operation == "diagnostics":
            return self.budget.report()
        if operation == "close":
            try:
                self.client.close()
            finally:
                fast_path = getattr(self.budget, 'short_embedding_input', None)
                if fast_path is not None:
                    fast_path.close()
                sdk_observation=getattr(self.budget,'sdk_observation',None)
                if sdk_observation is not None:
                    sdk_observation.close()
            self.client = None
            return {"closed":True}
        if operation in ManagementRPC.OPERATIONS:
            self.budget.operation = operation
            return self.management.execute(operation,arguments)
        if operation not in {"add", "search", "get_user_profile", "get", "list_memories"}:
            raise ValueError("hy_worker_operation_not_allowed")
        arguments = dict(arguments)
        if operation == "get_user_profile" and (set(arguments)!={"user_id"}
                or arguments["user_id"]!=self.settings.user_id):
            raise ValueError("hy_profile_user_scope_invalid")
        self.budget.operation = operation
        if operation == "add":
            if (arguments.get("user_id")!=self.settings.user_id
                    or arguments.get("agent_id")!=self.settings.agent_id
                    or arguments.get("source")!=SOURCE_NAMESPACE):
                raise ValueError("hy_add_owner_scope_invalid")
            arguments["memory_at"] = datetime.fromisoformat(arguments["memory_at"])
        response=getattr(self.client, operation)(**arguments)
        if operation=="search":
            response=enrich_search(self.client,response,arguments.get("user_ids",[]))
        elif operation=="get_user_profile":
            response=enrich_profile(self.client,response,arguments["user_id"])
        return response


def main(*, service=None):
    service = service or ProtocolService()
    output = sys.stdout
    with open(os.devnull, "w", encoding="utf-8") as sink:
        while True:
            line = sys.stdin.readline(MAX_LINE + 1)
            if not line or len(line) > MAX_LINE:
                break
            request_id = None
            operation = None
            observation = None
            try:
                request = json.loads(line)
                request_id, operation = request["id"], request["operation"]
                with redirect_stdout(sink), redirect_stderr(sink):
                    identity=request.get('observation_id')
                    if isinstance(identity,str) and len(identity) in range(24,33) and all(c in '0123456789abcdef' for c in identity):
                        observation=Observation(identity)
                        with observation.activate(), span('sdk_execute_ms'):
                            operation_stage={'get_user_profile':'sdk_profile_ms','search':'sdk_search_ms','add':'sdk_add_ms'}.get(operation)
                            with span(operation_stage) if operation_stage else nullcontext():
                                result=service.execute(operation,request['arguments'])
                    else:
                        result = service.execute(operation, request["arguments"])
                response = {"id":request_id, "ok":True, "result":result}
                if observation is not None:
                    response['observation']=observation.snapshot()
                encoded = json.dumps(response, ensure_ascii=False)
                if len(encoded) > MAX_LINE:
                    raise ValueError("hy_response_too_large")
            except Exception as exc:
                response={"id":request_id,"ok":False,"error":"hy_worker_failed","error_type":type(exc).__name__}
                if observation is not None:
                    response['observation']=observation.snapshot()
                encoded=json.dumps(response)
            output.write(encoded + "\n")
            output.flush()
            if operation == "close":
                break
        if service.client is not None:
            # 父进程异常退出导致 stdin EOF 时也关闭 SDK，不留下后台 loop。
            try:
                with redirect_stdout(sink), redirect_stderr(sink):
                    service.client.close()
            except Exception:
                pass
