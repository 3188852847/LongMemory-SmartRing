"""固定074ca6d模型的协作取消与finally清理；不修改外部源码或解码数学。

上游tts在最后yield后才pop请求字典，提前close会跳过清理。此适配仅在核对
完整AST后把原清理移入finally，并让既有LLM迭代在token边界响应取消。
"""
import ast
import hashlib
import inspect
import textwrap
import threading
import time
from types import MethodType

TTS_AST = "06e43a328f0c2d5505016accf28a8772d141818480975e337a01eb3ef6a63b9a"
JOB_AST = "f17a7f03f1d20d412c8bab077995de1e4140bb175ee10bdd0a62d9aee1cfe87d"


class StreamCancelled(Exception):
    pass


def _tree(function):
    return ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]


def _digest(node):
    # Python3.12为FunctionDef增加空type_params字段；3.10没有该字段。
    # 仅规范这个无语义的空字段，不忽略任何实际参数、分支或调用。
    canonical = ast.dump(node, include_attributes=False).replace(', type_params=[]', '')
    return hashlib.sha256(canonical.encode()).hexdigest()


class StreamRuntime:
    def __init__(self):
        self.applied = False
        self.reason = "not_installed"
        self.external_cancel = None
        self.states = {}
        self.local = threading.local()
        self.lock = threading.Lock()
        self.last_producer_join_ms = None

    def begin(self, uuid):
        with self.lock:
            self.states[uuid] = {"stop": threading.Event(), "external": self.external_cancel,
                                 "error": None}

    def state(self, uuid):
        with self.lock:
            return self.states[uuid]

    @staticmethod
    def cancelled(state):
        return state["stop"].is_set() or (
            state["external"] is not None and state["external"].is_set())

    def check(self, uuid):
        state = self.state(uuid)
        if self.cancelled(state):
            raise StreamCancelled()
        if state["error"] is not None:
            raise RuntimeError("cosyvoice_token_producer_failed") from None

    def poll(self, uuid):
        # 保留训练chunk=25及后续25→50→100策略，仅减少CPU轮询的额外等待。
        self.check(uuid)
        self.state(uuid)["stop"].wait(.01)
        self.check(uuid)

    def finish(self, uuid, producer):
        started = time.perf_counter()
        state = self.state(uuid)
        state["stop"].set()
        # 不在生产者仍会访问字典时pop，也不允许下一段与旧GPU工作重叠。
        # 取消在token/GPU调用边界协作，不能承诺中止正在执行的CUDA kernel。
        if producer.ident is not None:
            producer.join()
        with self.lock:
            self.states.pop(uuid)
        self.last_producer_join_ms = round((time.perf_counter() - started) * 1000, 3)

    def snapshot(self):
        with self.lock:
            return {"applied": self.applied, "reason": self.reason,
                    "active_requests": len(self.states), "last_producer_join_ms": self.last_producer_join_ms}


def _adapt_tts(function, guard):
    """只包裹原来的请求启动、推理、清理切片；保持原token2wav调用不变。"""
    node = _tree(function)
    if _digest(node) != TTS_AST:
        raise ValueError("cosyvoice_tts_contract_changed")
    start = next(i for i, item in enumerate(node.body)
                 if isinstance(item, ast.Expr) and ast.unparse(item) == "p.start()")
    cleanup = next(i for i in range(start + 1, len(node.body))
                   if isinstance(node.body[i], ast.With))

    class Checks(ast.NodeTransformer):
        def visit_Expr(self, item):
            spelling = ast.unparse(item)
            if spelling == "time.sleep(0.1)":
                return ast.parse("_project_stream.poll(this_uuid)").body[0]
            if spelling == "p.join()":
                return [item, ast.parse("_project_stream.check(this_uuid)").body[0]]
            if isinstance(item.value, ast.Yield):
                return [ast.parse("_project_stream.check(this_uuid)").body[0], item]
            return self.generic_visit(item)

    body = []
    checks = Checks()
    for item in node.body[start:cleanup]:
        changed = checks.visit(item)
        body.extend(changed if isinstance(changed, list) else [changed])
    final = ast.parse("_project_stream.finish(this_uuid, p)").body + node.body[cleanup:]
    node.body = node.body[:start] + ast.parse("_project_stream.begin(this_uuid)").body + [
        ast.Try(body=body, handlers=[], orelse=[], finalbody=final)]
    namespace = {**function.__globals__, "_project_stream": guard}
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, "<project-cosyvoice-stream-finally>", "exec"), namespace)
    return namespace[node.name]


def install_stream_runtime(model):
    guard = StreamRuntime()
    try:
        if (type(model).__name__ != "CosyVoice3Model"
                or type(model).__module__ != "cosyvoice.cli.model"
                or any(name in vars(model) for name in ("tts", "llm_job"))):
            raise ValueError("cosyvoice_stream_model_unsupported")
        original_job = model.llm_job
        if _digest(_tree(original_job)) != JOB_AST:
            raise ValueError("cosyvoice_llm_job_contract_changed")
        patched_tts = _adapt_tts(model.tts, guard)
        methods = {}
        for name in ("inference", "inference_bistream"):
            method = getattr(model.llm, name, None)
            if not callable(method) or name in vars(model.llm):
                raise ValueError("cosyvoice_stream_llm_unsupported")
            methods[name] = method
    except ValueError as error:
        guard.reason = str(error) if str(error) in {
            'cosyvoice_stream_model_unsupported', 'cosyvoice_llm_job_contract_changed',
            'cosyvoice_tts_contract_changed', 'cosyvoice_stream_llm_unsupported'} else 'unsupported_fixed_stream_contract'
        return guard
    except (OSError, TypeError, SyntaxError, StopIteration):
        guard.reason = "unsupported_fixed_stream_contract"
        return guard

    def wrap_tokens(original):
        def tokens(*args, **kwargs):
            state = getattr(guard.local, "state", None)
            iterator = original(*args, **kwargs)
            try:
                while True:
                    # next本身会进入原模型计算；已知取消时不再推进另一个token。
                    if state is not None and guard.cancelled(state):
                        break
                    try:
                        token = next(iterator)
                    except StopIteration:
                        break
                    if state is not None and guard.cancelled(state):
                        break
                    yield token
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
        return tokens

    def job(self, *args, **kwargs):
        uuid = kwargs.get("uuid", args[-1] if args else None)
        state = guard.state(uuid)
        guard.local.state = state
        try:
            original_job(*args, **kwargs)
        except Exception as error:
            state["error"] = type(error).__name__  # 不保留供应商异常正文。
        finally:
            guard.local.state = None
            self.llm_end_dict[uuid] = True

    for name, original in methods.items():
        setattr(model.llm, name, wrap_tokens(original))
    model.llm_job = MethodType(job, model)
    model.tts = MethodType(patched_tts, model)
    guard.applied, guard.reason = True, "fixed_074ca6d_finally_and_token_cancel"
    return guard
