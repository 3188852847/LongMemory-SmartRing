import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
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

  test('快照标明读取时间且音量刻度使用固件允许上限', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/device/snapshot') return {
        volume: 30, battery: {level: 72, charging: true}, network: {signal: 'strong'},
      };
      return {
        connection_count: 1, ready: true, read_volume_supported: true, set_volume_supported: true,
        read_status_supported: true, set_brightness_supported: false, set_theme_supported: false,
        allowed_volume: {minimum: 5, maximum: 60},
      };
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);

    await waitFor(() => expect(screen.getByText('已连接')).toBeTruthy());
    expect(screen.getByText('/ 60')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: '读取设备快照'}));
    expect(await screen.findByText('72% · 充电中')).toBeTruthy();
    expect(screen.getByText(/读取于 .*不是持续监测；为保护隐私不显示 Wi‑Fi 名称/)).toBeTruthy();
    expect(screen.getByText('单次读取')).toBeTruthy();

    view.unmount();
    client.clear();
  });

  test('展示脱敏的圆屏首句分段而不声称包含 ASR 或真实播放', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1, ready:true, read_volume_supported:true, set_volume_supported:true,
      read_status_supported:true, set_brightness_supported:false, set_theme_supported:false,
      allowed_volume:{minimum:5,maximum:60},
      voice_latency:{version:1,state:'first_audio_sent',started_at:'2026-09-10T01:00:00+00:00',tts_backend:'voxcpm2',timings_ms:{
        memory_ready_ms:80,llm_requested_ms:90,llm_first_output_ms:590,tts_started_ms:790,
        audio_ready_ms:1790,first_audio_sent_ms:1810,response_completed_ms:2100,
      }},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('最近一次圆屏首句时序')).toBeTruthy();
    expect(screen.getByText('1.00 秒')).toBeTruthy();
    expect(screen.getByText(/不含录音与 ASR，也不代表扬声器真正开始出声/)).toBeTruthy();
    expect(screen.getByText(/当前后端：VoxCPM2/)).toBeTruthy();
    view.unmount(); client.clear();
  });
});
