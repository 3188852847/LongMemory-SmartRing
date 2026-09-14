import {describe, expect, test, vi} from 'vitest';
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {deviceSkinErrorCopy, RoundDisplayApp, resolveRoundDisplay} from './RoundDisplayApp';
import {ApiError, ChatApi} from './api';
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

  test('能力检测区分重启离线、操作占用和协议读取失败', () => {
    expect(deviceSkinErrorCopy(new ApiError('device_offline', 409)).title).toBe('圆屏当前离线');
    expect(deviceSkinErrorCopy(new ApiError('operation_busy', 409)).title).toBe('设备操作尚未结束');
    expect(deviceSkinErrorCopy(new ApiError('round_skin_readback_invalid', 409)).title).toBe('未能读取真机皮肤能力');
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
    const request=vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if(path==='/api/round-wallpapers') return {enabled:true,tool_state:'ready',max_upload_bytes:805306368,items:[],
        device_delivery:{enabled:true,requires_online_device:true,restart_after_publish:true}};
      if(path==='/api/round-wallpapers/device') return {wallpaper_api:1,active_valid:true,active_slot:'a',
        active_wallpaper_id:`wallpaper-${'b'.repeat(20)}`,active_sha256:'c'.repeat(64),active_size_bytes:1234,rollback_available:true};
      return skinPayload;
    });
    const queryClient=createConsoleQueryClient();
    render(<QueryClientProvider client={queryClient}><MemoryRouter><RoundDisplayApp/></MemoryRouter></QueryClientProvider>);
    expect(screen.getByRole('heading', {name: '圆屏状态预览'})).toBeTruthy();
    expect(screen.getByText(/画布：360 × 360 px/)).toBeTruthy();
    expect(screen.getByText('预览与真机采用同一版皮肤清单')).toBeTruthy();
    expect(screen.getByRole('region', {name: '圆屏模拟画布'})).toBeTruthy();
    expect(screen.getByText('1. 交互阶段')).toBeTruthy();
    expect(screen.getByText('2. 情绪表达')).toBeTruthy();
    expect(screen.getByText('3. 系统覆盖')).toBeTruthy();
    expect(screen.getByText('4. 皮肤档案')).toBeTruthy();
    expect(screen.getByText('当前编辑/预览')).toBeTruthy();
    expect(screen.getByText('网页保存选择')).toBeTruthy();
    expect(screen.getByText('最近真机回读')).toBeTruthy();
    expect(screen.getByText('真机显示模式')).toBeTruthy();
    expect(await screen.findByText('动态壁纸')).toBeTruthy();
    expect(screen.getByText('皮肤当前被覆盖')).toBeTruthy();
    const useSkinDisplay=screen.getByRole('button', {name:'切换为皮肤显示（会重启）'});
    expect(useSkinDisplay).toBeTruthy();
    expect(screen.getByText('不会自动检测')).toBeTruthy();
    expect(screen.getByText('5. 真机五态观察')).toBeTruthy();
    expect(screen.getByText('6. 动态壁纸素材库')).toBeTruthy();
    expect(screen.getByText('先检测真机皮肤能力')).toBeTruthy();
    expect(screen.getByRole('button', {name:'检测真机皮肤能力'})).toBeTruthy();
    expect((screen.getByRole('button', {name:'应用到真机'}) as HTMLButtonElement).disabled).toBe(true);
    request.mockResolvedValueOnce({wallpaper_api:1,slot:'a',wallpaper_id:`wallpaper-${'b'.repeat(20)}`,
      sha256:'c'.repeat(64),size_bytes:1234,state:'skin_mode_restarting',operation_id:'d'.repeat(32)});
    fireEvent.click(useSkinDisplay);
    await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/round-wallpapers/deactivate','POST'));
    expect(await screen.findByText('切换指令已发送，正在等待圆屏重连')).toBeTruthy();
    const reconnecting=screen.getByRole('button', {name:'等待圆屏重连'});
    expect(reconnecting.classList.contains('ant-btn-loading')).toBe(false);
    const edit = screen.getByRole('button', {name:'从当前皮肤开始编辑'}) as HTMLButtonElement;
    await waitFor(() => expect(edit.disabled).toBe(false));
    fireEvent.click(edit);
    expect(screen.getByRole('region', {name:'本机自定义皮肤编辑器'})).toBeTruthy();
    expect(screen.getByLabelText('皮肤颜色：聆听')).toBeTruthy();
    expect(screen.getByRole('button', {name:'保存为“我的自定义皮肤”'})).toBeTruthy();

    request.mockResolvedValueOnce({skin_api:1,skin_id:'rose-night-v1',manifest_sha256:'a'.repeat(64)});
    act(() => queryClient.setQueryData(['round-wallpapers','device'], {
      wallpaper_api:1,active_valid:false,active_slot:'',active_wallpaper_id:'',
      active_sha256:'',active_size_bytes:0,rollback_available:true,
    }));
    expect(await screen.findByText('已确认切换为皮肤显示')).toBeTruthy();
    await screen.findByText(/真机支持皮肤协议/);
    expect(screen.getByText('与当前预览一致')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox',{name:'待机'}));
    expect(await screen.findByText(/观察记录已保存在当前浏览器/)).toBeTruthy();
    expect(localStorage.getItem(`longmemory:round-display-observations:v1:rose-night-v1:${'a'.repeat(64)}`)).toContain('idle');
  });
});
