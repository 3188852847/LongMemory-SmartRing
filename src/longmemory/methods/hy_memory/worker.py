"""仅供独立解释器启动的 SDK worker；stdout 只写协议，不回传 SDK 错误正文。"""

from contextlib import redirect_stdout, redirect_stderr, nullcontext
from contextvars import ContextVar
from datetime import datetime
from importlib import metadata
import json
import os
import platform
from pathlib import Path
import socket
import sys
from threading import Lock, local
from time import perf_counter
from urllib.parse import urlsplit

from .process_client import MAX_LINE
from .sdk_bridge import SDK_VERSION
from .settings import HySettings
from .source_evidence import enrich_profile,enrich_search
from .management_rpc import ManagementRPC, profile_scope_proof
from .layer_data import LayerDataRPC
from .sdk_bridge import SOURCE_NAMESPACE
from .observation import Observation, span
from .semantic import SemanticCoordinator, read_intentions, graph_evidence, read_profile, SearchSourceReader, invalidate_inactive_semantics
from .candidate_snapshot import CandidateSnapshots


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
        self._operation = ContextVar("hy_budget_operation", default=None)

    @property
    def operation(self):
        return self._operation.get()

    @operation.setter
    def operation(self, value):
        self._operation.set(value)

    def check_management_request(self, url):
        if getattr(self,"operation",None) in CandidateSnapshots.OPERATIONS:
            raise RuntimeError("hy_candidate_model_denied")
        if getattr(self, "operation", None) in LayerDataRPC.OPERATIONS:
            raise RuntimeError("hy_layer_data_model_denied")
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
                "semantic_local_prepared_ms":getattr(self,"semantic_local_prepared_ms",None),
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


def create_sdk(settings, workspace, *, create, short_embedding_fast_path=True, prepare_local_backends=True, synthetic_responder=None):
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
    if settings.semantic_layers_enabled and Path.cwd().resolve() != workspace.resolve():
        raise ValueError("hy_semantic_worker_cwd_must_be_owned_workspace")
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
        # Kuzu 0.11.3 Windows 原生窄字符API不能打开中文绝对路径；子进程
        # cwd 已由 parent 固定为独占workspace，ASCII相对路径仍在同一库内。
        "graph_store":{"db_path":"sdk/graph" if settings.semantic_layers_enabled else str(sdk / "graph")},
        "cache":{"backend":"sqlite", "db_path":str(sdk / "cache.db"),
                 "enable_profile_cache":False, "enable_system2_queue":False, "enable_intention_cache":False},
        "history":{"enable":False, "db_path":str(sdk / "history.db"), "record_searches":False},
        "coding":{"enable":False, "db_path":str(sdk / "coding.db")},
        # 2.0.3 LLM 的 max_retries 实际是总尝试次数，1 才是单次、无重试。
        "llm":{**endpoint(settings.llm), "max_retries":1, "max_tokens":settings.max_output_tokens,
               "agent_max_tokens":settings.max_output_tokens, "enable_query_rewrite":False, "enable_intention":settings.semantic_layers_enabled},
        "embedder":{**endpoint(settings.embedding), "embedding_dims":settings.embedding_dimensions},
        "recall":{"strength_enabled":False, "access_tracking_enabled":False,
                  "retrieval_clauses_enabled":False},
        "enable_graph":settings.semantic_layers_enabled, "metrics_enabled":False, "debug":False,
    })
    # fixture可注入多阶段模型替身，但生产settings/RPC不能提供可执行responder。
    mock_response = synthetic_response if synthetic_responder is None else lambda request: synthetic_responder(request, budget)
    config.http_transport_factory = (lambda: httpx.MockTransport(mock_response)) if settings.model_mode == "synthetic_transport" else BoundedTransport
    if settings.semantic_layers_enabled:
        # Windows已复现：Kuzu启动后才在SDK loop首次加载SciPy BLAS可卡在原生
        # 模块导入。先在初始化主线程加载本机已安装CPU聚类依赖，不落在聊天路径。
        started = perf_counter()
        from sklearn.cluster import DBSCAN  # noqa: F401
        import scipy.linalg  # noqa: F401
        budget.semantic_local_prepared_ms = (perf_counter()-started)*1000
    client = HyMemoryClient(config=config, mode="ultra" if settings.semantic_layers_enabled else "pro")
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
            create=create,fresh=fresh,verified=budget.management_update_verified or settings.semantic_layers_enabled)
        if settings.semantic_layers_enabled:
            from .management_rpc import owner_lease_held
            if (not budget.management_profile_scope_proven or not owner_lease_held(workspace)
                    or not getattr(client._graph_store, "_available", False)):
                raise ValueError("hy_semantic_scope_or_graph_unproven")
            budget.semantic = SemanticCoordinator(client, settings, workspace)
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
            self.candidates = CandidateSnapshots(self.client,self.settings,self.budget)
            return {"ready":True, "sdk_version":SDK_VERSION}
        if self.client is None:
            raise ValueError("hy_worker_not_initialized")
        if operation == "diagnostics":
            return self.budget.report()
        if operation == "close":
            try:
                semantic = getattr(self.budget, "semantic", None)
                if semantic is not None and not semantic.close():
                    # 不能在仍有原生写的 SDK 上 close；父进程将有界终止 worker，
                    # 持久 running 留待重启判 uncertain。
                    raise RuntimeError("hy_semantic_close_active")
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
            if operation in {"update","delete"}:
                self.candidates.changed()
            self.budget.operation = operation
            return self.management.execute(operation,arguments)
        if operation in CandidateSnapshots.OPERATIONS:
            self.budget.operation = operation
            return self.candidates.execute(operation,arguments)
        if operation in LayerDataRPC.OPERATIONS:
            self.budget.operation = operation
            return LayerDataRPC(self.client, self.settings, self.budget).execute(operation, arguments)
        if operation in SemanticCoordinator.OPERATIONS:
            semantic = getattr(self.budget, "semantic", None)
            if semantic is None:
                if operation == "semantic_status" and not arguments:
                    return {"protocol": 2, "enabled": False, "mode": "pro", "schema_state": "disabled",
                        "desired_enabled": False, "graph_available": False, "task_counts": {}, "paused": True,
                        "management_available": False, "last_task_finished_at": None, "epoch": None, "ready_epoch": None,
                        "native_evolve_idempotent": False, "automatic_restart_replay": False,
                        "intention_read": "disabled", "expired_intention_policy": "disabled",
                        "execution_authorized": False, "proactive_contact_enabled": False}
                raise ValueError("hy_semantic_not_enabled")
            if operation == "semantic_status" and not arguments:
                return semantic.status()
            if operation == "semantic_task" and set(arguments) == {"task_id"}:
                return semantic.task(arguments["task_id"])
            if operation == "semantic_cancel" and set(arguments) == {"task_id"}:
                return semantic.cancel(arguments["task_id"])
            if operation == "semantic_pause" and set(arguments) == {"paused"}:
                return semantic.pause(arguments["paused"])
            if operation == "semantic_enqueue" and set(arguments) <= {"task_id", "kind", "max_batches"} and "task_id" in arguments:
                if not self.settings.management_writes_enabled or semantic.gate()["paused"]:
                    raise ValueError("hy_semantic_write_denied")
                return semantic.enqueue(arguments["task_id"], kind=arguments.get("kind", "evolve"), max_batches=arguments.get("max_batches", 1))
            raise ValueError("hy_semantic_arguments_invalid")
        if operation not in {"add", "search", "get_user_profile", "get", "list_memories"}:
            raise ValueError("hy_worker_operation_not_allowed")
        arguments = dict(arguments)
        if operation == "get_user_profile" and (set(arguments)!={"user_id"}
                or arguments["user_id"]!=self.settings.user_id):
            raise ValueError("hy_profile_user_scope_invalid")
        self.budget.operation = operation
        if operation == "add":
            self.candidates.changed()
            if (arguments.get("user_id")!=self.settings.user_id
                    or arguments.get("agent_id")!=self.settings.agent_id
                    or arguments.get("source")!=SOURCE_NAMESPACE):
                raise ValueError("hy_add_owner_scope_invalid")
            arguments["memory_at"] = datetime.fromisoformat(arguments["memory_at"])
        semantic = getattr(self.budget, "semantic", None)
        if operation == "add" and semantic is not None:
            if semantic.gate()["paused"]:
                raise ValueError("hy_semantic_write_paused")
            semantic.dirty()
        elif operation == "add":
            invalidate_inactive_semantics(getattr(self.budget,"management_workspace",None))
        if operation == "search" and semantic is not None:
            # 普通读只使用原生普通通道；共享一次查询向量给无副作用 L7 读取。
            # L6 后台运行/失效期间不读图；不在问答路径触发归纳或到期写入。
            arguments["intention_limit"] = 0
            arguments["schema_limit"] = 3 if semantic.gate()["schema_state"] == "ready" else 0
            arguments["query_embedding"] = self.client._search_loop_thread.run(self.client._embed_service.embed(arguments["query"]))
        response = (self.client._search_loop_thread.run(read_profile(self.client,self.settings,self.budget))
            if operation == "get_user_profile" and semantic is not None else getattr(self.client, operation)(**arguments))
        if operation == "add" and semantic is not None and response.get("success") is True:
            semantic.after_add(arguments["request_id"])
        if operation=="search":
            if semantic is not None:
                # 归纳启动/新写入可与 search 并行；读取结束再核对失效门。
                if semantic.gate()["schema_state"] != "ready":
                    response["memories"]["schema"] = []
                else:
                    proven = []
                    for row in response["memories"]["schema"]:
                        node = self.client._search_loop_thread.run(self.client._graph_store.get_node(row["memory_id"]))
                        if (node is None or node.user_id != self.settings.user_id or node.agent_id != self.settings.agent_id
                                or node.source != SOURCE_NAMESPACE):
                            continue
                        meta, evidence = self.client._search_loop_thread.run(graph_evidence(self.client, self.settings, node))
                        if meta:
                            row.update(meta=meta, evidence_memory_ids=evidence)
                            proven.append(row)
                    response["memories"]["schema"] = proven if semantic.gate()["schema_state"] == "ready" else []
                response["memories"]["proactive"] = self.client._search_loop_thread.run(read_intentions(
                    self.client, self.settings, arguments["query_embedding"]))
            response=enrich_search(SearchSourceReader(self.client,self.settings) if semantic is not None else self.client,
                response,arguments.get("user_ids",[]))
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
                    semantic = getattr(service.budget, "semantic", None)
                    if semantic is None or semantic.close():
                        service.client.close()
            except Exception:
                pass
