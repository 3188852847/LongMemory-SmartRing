"""同源受控后台路由及无预留准入建议；不修改模型/来源身份。"""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


class BackgroundLane:
    def __init__(self, settings):
        self.settings = settings
        self.enabled = settings.background_priority_enabled
        self._active = ContextVar("hy_background_lane", default=False)
        self._lock = Lock()
        self.checks = 0
        self.last_reason = None
        # HySettings已经限定managed回环地址、授权和精确前台path；别名不接受外部URL。
        base = settings.llm.base_url.rstrip("/")
        self.chat_url = base[:-len("/hy/v1")]+"/hy-background/v1/chat/completions" if self.enabled else None
        self.admission_url = base[:-len("/hy/v1")]+"/hy-background/v1/admission" if self.enabled else None

    def eligible(self):
        if not self.enabled:
            return True
        import httpx
        eligible, reason = False, "admission_unavailable"
        try:
            # 建议查询不经过模型预算reserve，也不持任务工作锁；最多2秒，不重试/重定向。
            with httpx.Client(timeout=2,trust_env=False,follow_redirects=False) as client:
                response = client.get(self.admission_url,headers={"Authorization":"Bearer "+self.settings.llm.api_key})
            if response.status_code == 200 and len(response.content) <= 1024:
                value = response.json()
                if (isinstance(value,dict) and set(value)=={"version","eligible","reason_code"}
                        and type(value["version"]) is int and value["version"] == 1
                        and type(value["eligible"]) is bool
                        and value["reason_code"] in {None,"closed","requests_waiting","model_busy"}
                        and value["eligible"] == (value["reason_code"] is None)):
                    eligible, reason = value["eligible"], value["reason_code"]
        except (httpx.HTTPError,ValueError,TypeError):
            pass
        with self._lock:
            self.checks += 1
            self.last_reason = reason
        return eligible

    @contextmanager
    def operation(self):
        token = self._active.set(True)
        try:
            yield
        finally:
            self._active.reset(token)

    def route(self, request):
        if (self.enabled and self._active.get()
                and str(request.url) == self.settings.llm.base_url.rstrip("/")+"/chat/completions"):
            request.url = type(request.url)(self.chat_url)

    def snapshot(self):
        with self._lock:
            return {"enabled":self.enabled,"admission_checks":self.checks,"last_reason":self.last_reason,
                "admission_reserves_model":False,"routing":"owned_background_alias" if self.enabled else "default"}
