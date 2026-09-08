import {describe, expect, test, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {RoundDisplayApp, resolveRoundDisplay} from './RoundDisplayApp';
import {ChatApi} from './api';
import {createConsoleQueryClient} from './queryClient';

describe('圆屏状态协议与模拟器', () => {
  test('阻塞性系统状态覆盖普通交互状态', () => {
    expect(resolveRoundDisplay('speaking', 'network_offline')).toMatchObject({title: '网络未连接', focus: 'notice'});
    expect(resolveRoundDisplay('thinking', 'updating')).toMatchObject({title: '正在更新', focus: 'progress'});
  });

  test('充电与低电量不覆盖当前交互焦点', () => {
    expect(resolveRoundDisplay('listening', 'charging').title).toBe('聆听中');
    expect(resolveRoundDisplay('speaking', 'low_battery').title).toBe('回应中');
  });

  test('默认页面明确模拟边界并提供皮肤档案入口', () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      enabled:true, selected_skin:'rose-night-v1', skins:[],
      delivery:{console_preview:true, upstream_assets_ota_detected:true, device_apply_supported:false,
        device_delivery_implemented:true, reason:'device_capability_probe_required', known_firmware_baseline:'round-face-0004'},
    });
    render(<QueryClientProvider client={createConsoleQueryClient()}><MemoryRouter><RoundDisplayApp/></MemoryRouter></QueryClientProvider>);
    expect(screen.getByRole('heading', {name: '圆屏状态预览'})).toBeTruthy();
    expect(screen.getByText(/画布：360 × 360 px/)).toBeTruthy();
    expect(screen.getByText('预览与真机采用同一版皮肤清单')).toBeTruthy();
    expect(screen.getByRole('region', {name: '圆屏模拟画布'})).toBeTruthy();
    expect(screen.getByText('1. 交互阶段')).toBeTruthy();
    expect(screen.getByText('2. 情绪表达')).toBeTruthy();
    expect(screen.getByText('3. 系统覆盖')).toBeTruthy();
    expect(screen.getByText('4. 皮肤档案')).toBeTruthy();
    expect(screen.getByRole('button', {name:'检测真机皮肤能力'})).toBeTruthy();
    expect((screen.getByRole('button', {name:'应用到真机'}) as HTMLButtonElement).disabled).toBe(true);
  });
});
