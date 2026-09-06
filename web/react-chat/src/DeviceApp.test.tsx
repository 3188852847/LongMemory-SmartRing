import {afterEach, describe, expect, test, vi} from 'vitest';
import {render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi} from './api';
import {DeviceApp} from './DeviceApp';
import {createConsoleQueryClient} from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('设备与状态页', () => {
  test('设备离线时显示唤醒提示并禁止音量操作', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count: 0,
      ready: false,
      read_volume_supported: false,
      set_volume_supported: false,
      allowed_volume: {minimum: 5, maximum: 60},
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('请唤醒圆屏')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', {name:'读取当前值'}).hasAttribute('disabled')).toBe(true));
    expect(screen.getByText(/不需要重新配网/)).toBeTruthy();
    view.unmount();
    client.clear();
  });
});
