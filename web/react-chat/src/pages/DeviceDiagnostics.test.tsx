import {afterEach, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {ApiError, ChatApi} from '../api';
import {createConsoleQueryClient} from '../app/queryClient';
import {syntheticResponse} from '../features/data-workspace/syntheticFixtures';
import {DeviceApp} from './DeviceApp';

afterEach(() => vi.restoreAllMocks());
test('设备诊断接入真实摘要路径；刷新失败保留未知结果且不重放业务', async () => {
  vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
  let summaryReads = 0;
  const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method) => {
    expect(!method || method === 'GET').toBe(true);
    if (path !== '/api/observability') return syntheticResponse(path, false) as never;
    if (++summaryReads > 1) throw new ApiError('console_timeout', 504);
    return {...syntheticResponse(path, false) as object, requests: [{request_id: 'a'.repeat(24),
      time: '2026-10-14T00:00:00Z', operation: 'device', stage: 'request',
      outcome: 'unknown', code: 'bridge_timeout', status: 504, duration_ms: 10, stages: []}]} as never;
  });
  const client = createConsoleQueryClient();
  const view = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/device']}><DeviceApp/></MemoryRouter></QueryClientProvider>);
  await screen.findByText('请唤醒圆屏');
  expect(summaryReads).toBe(0);
  fireEvent.click(screen.getByRole('button', {name: '语音时序与诊断'}));
  expect(await screen.findByText('执行结果未知，请重新读取状态')).toBeTruthy();
  expect(screen.getByText(/设备播放仍未确认/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name: '刷新摘要'}));
  expect(await screen.findByText('摘要暂不可读取')).toBeTruthy();
  expect(screen.getByText('执行结果未知，请重新读取状态')).toBeTruthy();
  await waitFor(() => expect(summaryReads).toBe(2));
  expect(request.mock.calls.every(([, method]) => !method || method === 'GET')).toBe(true);
  view.unmount(); client.clear();
});
