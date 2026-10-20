"""单一供应商身份的持久HTTP会话；不重试、不预请求、不保存响应。"""

import asyncio
from concurrent.futures import Future
from contextlib import contextmanager
from queue import Empty, Full, Queue
from threading import Event, Lock, RLock, Thread
from urllib.parse import urlsplit


MAX_BODY = 2_000_000
MAX_LINE = 131072
MAX_STREAM = 32 * MAX_BODY


class _Stream:
    def __init__(self):
        self.headers = Future()
        self.packets = Queue(maxsize=32)
        self.done = Event()
        self.task = None
        self.error = None
        self.abandoned = False
        self.notify = None


async def finish_before_cancel(awaitable):
    """重复取消也等实际清理完成；不把caller取消传播给资源回收任务。"""
    task = asyncio.ensure_future(awaitable)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


def _notify(state):
    callback = state.notify
    if callback is not None:
        try:
            callback()
        except RuntimeError:
            pass  # 消费者循环已关闭时不能从provider线程回显异常或正文。


class _AsyncResponse:
    """同一pump/会话的异步句柄；close确认指本地请求任务退出，不证明远端停算。"""

    def __init__(self, transport, payload):
        self.transport, self.payload = transport, payload
        self.state = _Stream()
        self.status = None
        self.content = self._lines()
        self.started = self.closed = False
        self._close_task = None
        self._available = None

    async def __aenter__(self):
        if self.started or self.closed:
            raise ValueError('provider_stream_already_used')
        loop = asyncio.get_running_loop()
        self._available = asyncio.Event()
        self.state.notify = lambda: loop.call_soon_threadsafe(self._available.set)
        try:
            self.transport._submit(lambda: self.transport._pump(self.payload, self.state))
            self.started = True
            self.status = await asyncio.wrap_future(self.state.headers)
            return self
        except BaseException:
            await self.aclose()
            raise

    async def _lines(self):
        while not self.closed and not self.state.abandoned:
            self._available.clear()
            try:
                line = self.state.packets.get_nowait()
            except Empty:
                if self.state.done.is_set():
                    if self.state.error is not None:
                        raise self.state.error from None
                    return
                await self._available.wait()
                continue
            yield line

    async def _close(self):
        self.state.abandoned = True
        if self.started:
            with self.transport._lock:
                if not self.transport._closed:
                    future = asyncio.run_coroutine_threadsafe(
                        self.transport._cancel_stream(self.state), self.transport._loop)
                else:
                    future = None
            if future is not None:
                try:
                    await asyncio.wrap_future(future)
                except asyncio.CancelledError:
                    # 全局shutdown也可能取消这个取消协程；仍以pump finally为确认。
                    pass
            def exited():
                return self.state.done.is_set() and self.state.task is not None and self.state.task.done()
            while not exited():
                self._available.clear()
                if not exited():
                    await self._available.wait()
        self.closed = True
        self.payload = b''
        self.state.notify = None
        while True:
            try:
                self.state.packets.get_nowait()
            except Empty:
                break
        if self._available is not None:
            self._available.set()

    async def aclose(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await finish_before_cancel(self._close_task)

    async def __aexit__(self, *args):
        await self.aclose()

    async def wait_closed(self):
        if self._close_task is not None:
            await finish_before_cancel(self._close_task)
        else:
            while not self.closed:
                await asyncio.sleep(.005)
        return {'owned_upstream_exited': True, 'provider_compute_stopped': False}


def _safe(error):
    return (ValueError('provider_stream_invalid') if isinstance(error, ValueError)
            else OSError('provider_stream_interrupted'))


class PersistentProviderTransport:
    """自管活动任务。Gateway须在关闭时调用close；每个实例只绑定一个端点/凭据。"""

    def __init__(self, settings, *, close_timeout=5.0):
        try:
            url = urlsplit(settings.base_url)
        except (TypeError, ValueError):
            raise ValueError('provider_transport_not_authorized') from None
        if (url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password
                or url.query or url.fragment or (url.scheme == 'http' and not settings.allow_http)):
            raise ValueError('provider_transport_not_authorized')
        if close_timeout <= 0:
            raise ValueError('provider_close_timeout_invalid')
        self._url = settings.base_url.rstrip('/') + '/chat/completions'
        self._authorization = 'Bearer ' + settings.api_key
        self._timeout = settings.timeout_seconds
        self._close_timeout = close_timeout
        self._lock, self._close_lock = RLock(), Lock()
        self._closed = False
        self._close_failed = False
        self._loop = self._thread = self._session = None

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _submit(self, factory):
        with self._lock:
            if self._closed:
                raise ValueError('provider_transport_closed')
            if self._thread is None:
                self._loop = asyncio.new_event_loop()
                self._thread = Thread(target=self._run, name='hy-provider-persistent', daemon=True)
                self._thread.start()
            return asyncio.run_coroutine_threadsafe(factory(), self._loop)

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=self._timeout, sock_read=self._timeout)
            self._session = aiohttp.ClientSession(timeout=timeout,
                connector=aiohttp.TCPConnector(keepalive_timeout=120),
                cookie_jar=aiohttp.DummyCookieJar(), read_bufsize=MAX_LINE, trust_env=False)
        return self._session

    def _post(self, session, payload):
        return session.post(self._url, data=payload, allow_redirects=False,
            headers={'Content-Type': 'application/json', 'Authorization': self._authorization})

    async def _send(self, payload):
        response = None
        completed = False
        try:
            session = await self._get_session()
            async with self._post(session, payload) as response:
                data = bytearray()
                while True:
                    chunk = await response.content.read(min(65536, MAX_BODY + 1 - len(data)))
                    if not chunk:
                        completed = True
                        return response.status, bytes(data)
                    data.extend(chunk)
                    if len(data) > MAX_BODY:
                        raise ValueError('provider_response_too_large')
        except BaseException as error:
            raise _safe(error) from None
        finally:
            if response is not None and not completed:
                response.close()

    def send(self, payload):
        future = self._submit(lambda: self._send(payload))
        try:
            return future.result()
        except Exception as error:
            raise _safe(error) from None

    async def _pump(self, payload, state):
        state.task = asyncio.current_task()
        state.task.add_done_callback(lambda task: _notify(state))
        response = None
        completed = False
        try:
            session = await self._get_session()
            async with self._post(session, payload) as response:
                if not state.headers.done():
                    state.headers.set_result(response.status)
                total = 0
                async for line in response.content:
                    total += len(line)
                    if len(line) > MAX_LINE or total > MAX_STREAM:
                        raise ValueError('provider_stream_too_large')
                    while True:
                        try:
                            state.packets.put_nowait(line)
                            _notify(state)
                            break
                        except Full:
                            await asyncio.sleep(0.001)
                completed = True
        except BaseException as error:
            state.error = _safe(error)
        finally:
            if response is not None and not completed:
                response.close()
            if not state.headers.done():
                state.headers.set_exception(state.error or OSError('provider_stream_interrupted'))
            state.done.set()
            _notify(state)

    def async_stream(self, payload):
        """只导出同一连接池的逐行异步句柄；不创建另一套HTTP会话。"""
        return _AsyncResponse(self, payload)

    async def _cancel_stream(self, state):
        if state.task is not None and not state.task.done():
            state.task.cancel()
            await asyncio.gather(state.task, return_exceptions=True)

    def _finish_stream(self, state):
        state.abandoned = True
        with self._lock:
            if self._closed:
                return
            future = asyncio.run_coroutine_threadsafe(self._cancel_stream(state), self._loop)
        try:
            future.result(timeout=self._close_timeout)
        except Exception:
            # 全局close可能同时取消本次清理协程；pump已结束才可确认清理。
            if self._closed and state.done.wait(timeout=self._close_timeout):
                return
            raise RuntimeError('provider_stream_close_unconfirmed') from None

    @contextmanager
    def stream(self, payload):
        state = _Stream()
        self._submit(lambda: self._pump(payload, state))
        def lines():
            while not state.abandoned:
                if self._closed:
                    raise OSError('provider_stream_interrupted') from None
                try:
                    line = state.packets.get(timeout=0.05)
                except Empty:
                    if state.done.is_set():
                        if state.error is not None:
                            raise state.error from None
                        return
                    continue
                if state.abandoned:
                    return
                yield line
        try:
            try:
                status = state.headers.result(timeout=self._timeout + 1)
            except Exception as error:
                raise _safe(error) from None
            yield status, lines()
        finally:
            self._finish_stream(state)

    async def _shutdown(self):
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._session is not None:
            await self._session.close()

    def close(self):
        with self._close_lock:
            with self._lock:
                if self._closed:
                    if self._close_failed:
                        raise RuntimeError('provider_transport_close_unconfirmed')
                    return
                self._closed = True
                loop, thread = self._loop, self._thread
            if thread is None:
                return
            failed = False
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), loop).result(timeout=self._close_timeout)
            except Exception:
                failed = True
            finally:
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except RuntimeError:
                    failed = True
                thread.join(timeout=self._close_timeout)
            self._close_failed = failed or thread.is_alive()
            if self._close_failed:
                raise RuntimeError('provider_transport_close_unconfirmed') from None
