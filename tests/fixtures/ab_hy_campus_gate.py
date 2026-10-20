"""AB-CAMPUS专属硬门：发送前持久认领；无凭据、无自动重试。"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from time import time
from urllib.parse import urlsplit


AUTHORIZATION = "AB-CAMPUS-L6L7-20261021-01"
LLM_LIMIT = 6
HTTP_LIMIT = 38
OUTPUT_LIMIT = 512
WALL_SECONDS = 240
KINDS = {"sdk_embedding", "sdk_llm", "school_llm"}


class GateStopped(RuntimeError):
    pass


class HardGate:
    def __init__(self, path, *, create=False, started=None):
        self.path = Path(path).resolve()
        self.serial = RLock()
        if Path(path).is_symlink() or Path(path).is_junction():
            raise ValueError("ab_gate_link_denied")
        if create:
            with self.path.open("xb"):
                pass
            started = time() if started is None else started
            with self._db() as db:
                db.executescript("CREATE TABLE gate(authorization TEXT,started REAL,deadline REAL,halted INTEGER,reason TEXT);"
                    "CREATE TABLE attempts(id INTEGER PRIMARY KEY,kind TEXT,request_sha256 TEXT,output_limit INTEGER,state TEXT,started REAL,finished REAL,http_status INTEGER);"
                    "CREATE INDEX attempts_kind ON attempts(kind);")
                db.execute("INSERT INTO gate VALUES (?,?,?,0,NULL)",(AUTHORIZATION,started,started+WALL_SECONDS))
        if not self.path.is_file():
            raise FileNotFoundError("ab_gate_existing_file_required")
        with self._db() as db:
            rows = db.execute("SELECT authorization FROM gate").fetchall()
            if rows != [(AUTHORIZATION,)]:
                raise ValueError("ab_gate_authorization_mismatch")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path.as_uri()+"?mode=rw",uri=True,timeout=2)
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def halt(self, reason):
        if reason not in {"wall_deadline","llm_limit","http_limit","duplicate_model_request","usage_unknown",
                "provider_failed","output_usage_exceeded","probe_failed","completed","parent_disconnected"}:
            raise ValueError("ab_gate_reason_invalid")
        with self._db() as db:
            db.execute("UPDATE gate SET halted=1,reason=COALESCE(reason,?)",(reason,))

    def claim(self, kind, *, request_sha256=None, output_limit=None):
        if kind not in KINDS or (kind=="school_llm" and (not isinstance(request_sha256,str)
                or len(request_sha256)!=64 or type(output_limit) is not int or not 1<=output_limit<=OUTPUT_LIMIT)):
            raise ValueError("ab_gate_attempt_invalid")
        failure, identifier = None,None
        with self._db() as db:
            _,_,deadline,halted,reason = db.execute("SELECT * FROM gate").fetchone()
            count = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            llm = db.execute("SELECT COUNT(*) FROM attempts WHERE kind='school_llm'").fetchone()[0]
            if halted:
                failure = reason or "probe_failed"
            elif time()>=deadline:
                failure = "wall_deadline"
            elif count>=HTTP_LIMIT:
                failure = "http_limit"
            elif kind=="school_llm" and llm>=LLM_LIMIT:
                failure = "llm_limit"
            elif kind=="school_llm" and db.execute("SELECT 1 FROM attempts WHERE kind='school_llm' AND request_sha256=?",(request_sha256,)).fetchone():
                failure = "duplicate_model_request"
            if failure:
                db.execute("UPDATE gate SET halted=1,reason=COALESCE(reason,?)",(failure,))
            else:
                identifier = db.execute("INSERT INTO attempts(kind,request_sha256,output_limit,state,started) VALUES (?,?,?,'reserved',?)",
                    (kind,request_sha256,output_limit,time())).lastrowid
                reached = "http_limit" if count+1>=HTTP_LIMIT else "llm_limit" if kind=="school_llm" and llm+1>=LLM_LIMIT else None
                if reached:
                    db.execute("UPDATE gate SET halted=1,reason=COALESCE(reason,?)",(reached,))
        if failure:
            raise GateStopped("ab_gate_"+failure)
        return identifier

    def sdk_claim(self, url):
        parsed = urlsplit(str(url))
        if parsed.scheme!="http" or parsed.hostname!="127.0.0.1" or parsed.path not in {"/hy/v1/chat/completions","/hy/v1/embeddings"}:
            raise GateStopped("ab_gate_sdk_endpoint_denied")
        return self.claim("sdk_embedding" if parsed.path.endswith("/embeddings") else "sdk_llm")

    def sdk_finished(self, identifier, *, status):
        with self._db() as db:
            db.execute("UPDATE attempts SET state=?,finished=?,http_status=? WHERE id=? AND kind<>'school_llm'",
                ("completed" if status==200 else "unknown",time(),status,identifier))

    def finish(self, identifier, *, status=None):
        with self._db() as db:
            db.execute("UPDATE attempts SET state=?,finished=?,http_status=? WHERE id=?",
                ("completed" if status==200 else "unknown",time(),status,identifier))
            count = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            llm = db.execute("SELECT COUNT(*) FROM attempts WHERE kind='school_llm'").fetchone()[0]
            reason = "llm_limit" if llm>=LLM_LIMIT else "http_limit" if count>=HTTP_LIMIT else None
            if reason:
                db.execute("UPDATE gate SET halted=1,reason=COALESCE(reason,?)",(reason,))

    def snapshot(self):
        with self._db() as db:
            authorization,started,deadline,halted,reason = db.execute("SELECT * FROM gate").fetchone()
            kinds = dict(db.execute("SELECT kind,COUNT(*) FROM attempts GROUP BY kind"))
            rows = db.execute("SELECT id,kind,request_sha256,output_limit,state,http_status FROM attempts ORDER BY id").fetchall()
        return {"authorization":authorization,"started_at_unix":started,"deadline_unix":deadline,
            "halted":bool(halted),"reason_code":reason,"http_attempts":sum(kinds.values()),"attempts_by_kind":kinds,
            "actual_llm_attempts":kinds.get("school_llm",0),"limits":{"llm":LLM_LIMIT,"all_http":HTTP_LIMIT,
                "output_tokens":OUTPUT_LIMIT,"wall_seconds":WALL_SECONDS},
            "attempts":[dict(zip(("attempt_id","kind","request_sha256","max_tokens_sent","state","http_status"),row)) for row in rows]}


def clamp(body):
    if not isinstance(body,dict) or type(body.get("max_tokens")) is not int or body["max_tokens"]<=0 or body.get("stream",False) is not False:
        raise ValueError("ab_probe_payload_invalid")
    body = dict(body)
    body["max_tokens"] = min(body["max_tokens"],OUTPUT_LIMIT)
    for key in ("max_completion_tokens","max_output_tokens","best_of"):
        body.pop(key,None)
    body["n"] = 1
    body["thinking"] = {"type":"disabled"}
    return body


def gateway_type(base):
    class StrictGateway(base):
        def __init__(self, *, gate, raw_directory, remote=None, **kwargs):
            self.gate, self.raw_directory = gate,Path(raw_directory)
            self._probe_remote = remote
            super().__init__(remote=self._strict_remote,**kwargs)

        def embed(self, body, role):
            with self.gate.serial:
                # SDK出站已在发送前计数；这里不重复计算同一跳。
                if self.gate.snapshot()["halted"]:
                    raise GateStopped("ab_gate_halted")
                return super().embed(body,role)

        def complete(self, phase, body):
            with self.gate.serial:
                if phase!="hy":
                    raise ValueError("ab_probe_phase_denied")
                status,response = super().complete(phase,clamp(body))
                if status!=200:
                    self.gate.halt("provider_failed")
                if self.budget.status().get("unknown_or_inflight"):
                    self.gate.halt("usage_unknown")
                return status,response

        def _strict_remote(self, payload):
            # 在真正供应商发送点再次夹紧，外层参数不能绕过。
            payload = json.dumps(clamp(json.loads(payload)),ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()
            identifier = self.gate.claim("school_llm",request_sha256=hashlib.sha256(payload).hexdigest(),
                output_limit=json.loads(payload)["max_tokens"])
            status = None
            try:
                status,data = (self._probe_remote(payload) if self._probe_remote is not None else self._provider_transport.send(payload))
                # 只在忽略目录保留合成请求/模型正文；不保存Authorization或凭据。
                with (self.raw_directory/f"model-{identifier}-request.json").open("xb") as stream:
                    stream.write(payload)
                with (self.raw_directory/f"model-{identifier}-response.json").open("xb") as stream:
                    stream.write(data)
                parsed = json.loads(data)
                completion = (parsed.get("usage") or {}).get("completion_tokens")
                if type(completion) is int and completion>OUTPUT_LIMIT:
                    self.gate.halt("output_usage_exceeded")
                    raise GateStopped("ab_gate_output_usage_exceeded")
                return status,data
            finally:
                self.gate.finish(identifier,status=status)
    return StrictGateway
