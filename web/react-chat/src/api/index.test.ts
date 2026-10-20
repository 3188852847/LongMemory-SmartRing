import {afterEach, describe, expect, test, vi} from 'vitest';
import {ApiError, ChatApi} from './index.ts';

afterEach(() => vi.unstubAllGlobals());

describe('ChatApi', () => {
test('并发挂载的客户端共享一次会话建立，Cookie 与各自写请求的 CSRF 保持配对',async()=>{
  let sessions=0,cookieCsrf='';
  const writes:string[]=[];
  vi.stubGlobal('fetch',vi.fn(async(path,options)=>{
    if(path==='/api/session') {
      cookieCsrf=`synthetic-session-${++sessions}`;
      return new Response(JSON.stringify({csrf:cookieCsrf}));
    }
    const csrf=(options.headers as Record<string,string>)['X-Console-CSRF'];
    writes.push(csrf);
    return new Response(JSON.stringify(csrf===cookieCsrf?{saved:true}:{error:'csrf_rejected'}),{status:csrf===cookieCsrf?200:403});
  }));
  const first=new ChatApi(),second=new ChatApi();
  await Promise.all([first.bootstrap(),second.bootstrap()]);
  await expect(first.request('/api/chats/first/messages','POST',{text:'合成第一条'})).resolves.toEqual({saved:true});
  await expect(second.request('/api/chats/second/messages','POST',{text:'合成第二条'})).resolves.toEqual({saved:true});
  expect(sessions).toBe(1);
  expect(writes).toEqual([cookieCsrf,cookieCsrf]);
});

test('bootstrap and writes use CSRF without persisting or retrying content', async () => {
  const calls: {path: string; options?: RequestInit}[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path, options) => {
    calls.push({path: String(path), options});
    return new Response(JSON.stringify(calls.length === 1 ? {csrf:'synthetic'} : {error:'chat_busy'}), {status: calls.length === 1 ? 200 : 409});
  }));
  const api = new ChatApi(); await api.bootstrap();
  await expect(api.request('/api/chats/test/messages', 'POST', {text:'合成输入'})).rejects.toThrow(/chat_busy/);
  expect(calls).toHaveLength(2);
  expect((calls[1].options?.headers as Record<string,string>)['X-Console-CSRF']).toBe('synthetic');
  expect(calls[1].options?.credentials).toBe('same-origin');
});

test('并发会话建立失败不自动重试，下一次显式建立重新读取令牌',async()=>{
  const fetchMock=vi.fn().mockRejectedValueOnce(new Error('synthetic offline'))
    .mockResolvedValueOnce(new Response(JSON.stringify({csrf:'synthetic-recovered'})))
    .mockResolvedValueOnce(new Response(JSON.stringify({saved:true})));
  vi.stubGlobal('fetch',fetchMock);
  const first=new ChatApi(),second=new ChatApi();
  const failed=await Promise.allSettled([first.bootstrap(),second.bootstrap()]);
  expect(failed.map(result=>result.status)).toEqual(['rejected','rejected']);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await first.bootstrap();
  await expect(first.request('/api/chats/recovered/messages','POST',{text:'合成恢复'})).resolves.toEqual({saved:true});
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock.mock.calls[2][1].headers['X-Console-CSRF']).toBe('synthetic-recovered');
});

test('GET recovery does not replay a write', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_path, options) => {
    expect(options?.method).toBe('GET'); expect(options?.body).toBeUndefined();
    return new Response(JSON.stringify({pending: false, turns: []}));
  }));
  await expect(new ChatApi().request('/api/chats/test')).resolves.toEqual({pending:false, turns:[]});
});

test('non-JSON framework error is reduced to a safe HTTP category', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>not found</html>', {
    status: 404, headers: {'Content-Type': 'text/html'},
  })));
  const failure = await new ChatApi().request('/api/chats/missing').catch(error => error);
  expect(failure).toBeInstanceOf(ApiError);
  expect(failure).toMatchObject({code: 'http_404', status: 404});
});
});
