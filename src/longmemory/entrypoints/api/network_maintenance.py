"""启动器网络重开前的短时静默租约；不取消请求、不读取聊天正文。"""

import asyncio
import time
from aiohttp import web

PATH = '/api/internal/network-maintenance'


def owned_runtime_idle(runtime):
    """仅旁路检查可信Runtime现有句柄；未知形态或忙锁均拒绝，不调用模型/账本。"""
    if runtime is None:
        return True
    lock = getattr(runtime, '_lock', None)
    if lock is None or not lock.acquire(blocking=False):
        return False
    try:
        if getattr(runtime, '_closed', True) or getattr(runtime, '_closing', True):
            return False
        futures = getattr(runtime, '_deferred_futures', None)
        if futures is None or not all(future.done() for future in tuple(futures)):
            return False
        service = getattr(runtime, '_model_service', None)
        if service is None:
            return True
        gateway = getattr(service, 'gateway', None)
        connection_lock = getattr(gateway, '_connections_lock', None)
        if getattr(service, 'closed', True) or connection_lock is None or not connection_lock.acquire(blocking=False):
            return False
        try:
            return (getattr(gateway, '_closed', True) is False
                    and getattr(gateway, '_downstreams', None) == set()
                    and getattr(gateway, '_streams', None) == set())
        finally:
            connection_lock.release()
    finally:
        lock.release()


class NetworkMaintenance:
    def __init__(self, instance_id, *, clock=time.monotonic):
        self.instance_id, self.clock = instance_id, clock
        self.until = 0
        self.active = 0
        self.pending = set()
        self.idle_checks = []
        self.supported = False

    @web.middleware
    async def middleware(self, request, handler):
        if request.path == PATH:
            return await handler(request)
        if self.until > self.clock():
            return web.json_response({'error': 'network_restart_pending'}, status=503,
                                     headers={'Retry-After': '60'})
        self.active += 1
        task = asyncio.create_task(handler(request))
        self.pending.add(task)
        def completed(done):
            self.active -= 1
            self.pending.discard(done)
            if not done.cancelled():
                done.exception()  # 已断开客户端不再领取结果，也不能泄露后台异常正文。
        task.add_done_callback(completed)
        # 客户端断开不能把仍在执行的to_thread/写入错误地当成空闲。
        return await asyncio.shield(task)

    async def handle(self, request):
        if 'Origin' in request.headers or 'Sec-Fetch-Site' in request.headers:
            return web.json_response({'error': 'local_cli_only'}, status=403)
        data = await request.json()
        if (not self.instance_id or not isinstance(data, dict)
                or set(data) != {'instance', 'draining'}
                or data['instance'] != self.instance_id or type(data['draining']) is not bool):
            return web.json_response({'error': 'maintenance_identity_mismatch'}, status=409)
        if not data['draining']:
            self.until = 0
        elif (not self.supported or self.active
              or not all(check() is True for check in self.idle_checks)):
            return web.json_response({'error': 'network_restart_busy'}, status=409)
        else:
            # 同一事件循环中检查和加闸之间没有 await；后续请求不能越过空闲检查。
            self.until = self.clock() + 60
        return web.json_response({'instance': self.instance_id, 'draining': data['draining']})
