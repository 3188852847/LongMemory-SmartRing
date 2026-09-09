import {describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
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

  test('默认页面明确模拟边界并提供受限的本机皮肤编辑器', async () => {
    localStorage.clear();
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const skinPayload={
      enabled:true, selected_skin:'rose-night-v1', custom_skin_id:'local-custom-v1', skins:[{
        schema_version:1, id:'rose-night-v1', name:'蔷薇夜色', description:'测试皮肤',
        target:{board:'viewe-smartring-plus', width:360, height:360, color_format:'RGB565', skin_api:1},
        palette:{background:'#171B26', background_edge:'#090B10', foreground:'#F7F4F8', muted:'#CBD1DC', accent:'#DF72A8', listening:'#69D5FF', thinking:'#F7C65A', happy:'#7DE2B8', concerned:'#8AA8FF', warning:'#F0B34B', error:'#F16C73', charging:'#8DE39E'},
        face:{eye_width:22, eye_height:36, mouth_width:38}, motion:{blink_seconds:5.4, speaking_seconds:.52}, manifest_sha256:'a'.repeat(64),
      }],
      delivery:{console_preview:true, upstream_assets_ota_detected:true, device_apply_supported:false,
        device_delivery_implemented:true, reason:'device_capability_probe_required', known_firmware_baseline:'round-face-0004'},
    };
    const request=vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path =>
      path==='/api/round-wallpapers'
        ? {enabled:true,tool_state:'ready',max_upload_bytes:805306368,items:[],
          device_delivery:{enabled:false,requires_online_device:true,restart_after_publish:true}}
        : skinPayload
    );
    render(<QueryClientProvider client={createConsoleQueryClient()}><MemoryRouter><RoundDisplayApp/></MemoryRouter></QueryClientProvider>);
    expect(screen.getByRole('heading', {name: '圆屏状态预览'})).toBeTruthy();
    expect(screen.getByText(/画布：360 × 360 px/)).toBeTruthy();
    expect(screen.getByText('预览与真机采用同一版皮肤清单')).toBeTruthy();
    expect(screen.getByRole('region', {name: '圆屏模拟画布'})).toBeTruthy();
    expect(screen.getByText('1. 交互阶段')).toBeTruthy();
    expect(screen.getByText('2. 情绪表达')).toBeTruthy();
    expect(screen.getByText('3. 系统覆盖')).toBeTruthy();
    expect(screen.getByText('4. 皮肤档案')).toBeTruthy();
    expect(screen.getByText('5. 真机五态观察')).toBeTruthy();
    expect(screen.getByText('6. 动态壁纸素材库')).toBeTruthy();
    expect(screen.getByText('先检测真机皮肤能力')).toBeTruthy();
    expect(screen.getByRole('button', {name:'检测真机皮肤能力'})).toBeTruthy();
    expect((screen.getByRole('button', {name:'应用到真机'}) as HTMLButtonElement).disabled).toBe(true);
    const edit = screen.getByRole('button', {name:'从当前皮肤开始编辑'}) as HTMLButtonElement;
    await waitFor(() => expect(edit.disabled).toBe(false));
    fireEvent.click(edit);
    expect(screen.getByRole('region', {name:'本机自定义皮肤编辑器'})).toBeTruthy();
    expect(screen.getByLabelText('皮肤颜色：聆听')).toBeTruthy();
    expect(screen.getByRole('button', {name:'保存为“我的自定义皮肤”'})).toBeTruthy();

    request.mockResolvedValueOnce({skin_api:1,skin_id:'rose-night-v1',manifest_sha256:'a'.repeat(64)});
    fireEvent.click(screen.getByRole('button',{name:'检测真机皮肤能力'}));
    await screen.findByText(/真机支持皮肤协议/);
    fireEvent.click(screen.getByRole('checkbox',{name:'待机'}));
    expect(await screen.findByText(/观察记录已保存在当前浏览器/)).toBeTruthy();
    expect(localStorage.getItem(`longmemory:round-display-observations:v1:rose-night-v1:${'a'.repeat(64)}`)).toContain('idle');
  });
});
