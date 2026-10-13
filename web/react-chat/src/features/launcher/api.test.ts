import {afterEach, describe, expect, test, vi} from 'vitest';
import {consumeLauncherToken, LauncherApi} from './api';

afterEach(() => vi.unstubAllGlobals());
describe('启动面板控制权限', () => {
  test('从片段读取并立即去除令牌，不写入本地存储', () => {
    const replaceState = vi.fn();
    const token = 'a'.repeat(32);
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    expect(consumeLauncherToken({hash: `#token=${token}`, pathname: '/launcher', search: ''}, {replaceState})).toBe(token);
    expect(replaceState).toHaveBeenCalledWith(null, '', '/launcher');
    expect(storage).not.toHaveBeenCalled();
  });
  test('无令牌或异常令牌拒绝控制请求', async () => {
    const request = vi.fn(); vi.stubGlobal('fetch', request);
    expect(consumeLauncherToken({hash: '#token=invalid', pathname: '/launcher', search: ''}, {replaceState: vi.fn()})).toBe('');
    await expect(new LauncherApi('').request('actions', {action: 'start'})).rejects.toMatchObject({status: 401});
    expect(request).not.toHaveBeenCalled();
  });
  test('只在同源请求头中发送 Bearer，读取状态不产生写入', async () => {
    const request = vi.fn().mockResolvedValue({ok: true, json: async () => ({state: 'stopped'})});
    vi.stubGlobal('fetch', request);
    const token = 'b'.repeat(32); const api = new LauncherApi(token);
    await api.request('status');
    const [url, options] = request.mock.calls[0];
    expect(url).toBe('/api/launcher/status'); expect(url).not.toContain(token);
    expect(options.method).toBe('GET'); expect(options.body).toBeUndefined();
    expect(options.headers.Authorization).toBe(`Bearer ${token}`);
    expect(options.cache).toBe('no-store');
  });
  test('冲突不会自动重试或把服务端错误正文泄漏给用户', async () => {
    const request = vi.fn().mockResolvedValue({ok: false, status: 409}); vi.stubGlobal('fetch', request);
    await expect(new LauncherApi('c'.repeat(32)).request('settings', {settings: {voice: true}, expected_revision: 'old'})).rejects.toMatchObject({status: 409, message: '设置已被其他页面修改，请刷新后重新编辑。'});
    expect(request).toHaveBeenCalledTimes(1);
  });
});
