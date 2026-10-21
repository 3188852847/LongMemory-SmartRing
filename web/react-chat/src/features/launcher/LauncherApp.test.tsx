import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {LauncherApp} from './LauncherApp';
import {LauncherApi, LauncherError, type LauncherSnapshot} from './api';
import {AMBIENT_KEY} from '../../components/DigitalAtmosphere';

afterEach(() => {localStorage.removeItem(AMBIENT_KEY);});

const stopped: LauncherSnapshot = {
  state: 'stopped', message: '可以开启陪伴', services: [{id: 'console', label: '文字服务', state: '尚未启动'}],
  console_url: null, settings_revision: 'rev-1', can_start: true, can_stop: false,
  settings: {voice: false, model_profile: 'official', voice_model_profile: 'official', voice_mode: 'pipeline', voice_latency_mode: 'realtime', memory_extraction: 'llm', memory_retrieval: 'hybrid', memory_backend: 'longmemory', vad_profile: 'normal', start_page: 'chat', lan_ip: '', http_risk_ack: false, tts_backend: 'cosyvoice3'},
};
function fake(snapshot = stopped) {
  const api = new LauncherApi('a'.repeat(32));
  const request = vi.spyOn(api, 'request').mockResolvedValue(snapshot);
  return {api, request};
}

describe('Cosy声音交付选择与连接事实分开显示', () => {
  test('只保存显式选择，不触发启动或热切换', async () => {
    const value: LauncherSnapshot = {...stopped, settings: {...stopped.settings, voice: true, cosy_delivery_mode: 'buffered'}};
    const {api, request} = fake(value); render(<LauncherApp api={api}/>);
    fireEvent.click(await screen.findByRole('button', {name: /启动设置/}));
    fireEvent.click(screen.getByText('语音', {exact: true}));
    fireEvent.mouseDown(screen.getByLabelText('声音交付方式'));
    fireEvent.click(await screen.findByText('分段播放（候选）', {selector: '.ant-select-item-option-content'}));
    expect(request.mock.calls.every(call => call[0] === 'status')).toBe(true);
    fireEvent.click(screen.getByRole('button', {name: '保存设置'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('settings', {settings: {cosy_delivery_mode: 'incremental'}, expected_revision: 'rev-1'}));
    expect(request.mock.calls.some(call => call[0] === 'actions')).toBe(false);
  });

  test('准备值和启动值不冒充实际连接，运行中模式控件禁用', async () => {
    const value: LauncherSnapshot = {...stopped, state: 'ready', can_start: false, can_stop: true,
      settings: {...stopped.settings, voice: true, cosy_delivery_mode: 'adaptive'},
      cosy_delivery: {version: 1, next_start_mode: 'adaptive', next_start_source: 'preference', selection_valid: true,
        startup_mode: 'incremental', startup_source: 'preference', restart_required: true,
        observation: {version: 1, state: 'not_observed', effective_mode: 'incremental', restart_required: false, physical_playback_verified: false}}};
    const {api, request} = fake(value); render(<LauncherApp api={api}/>);
    const status = await screen.findByLabelText('声音交付状态');
    expect(status.textContent).toContain('下次启动：自适应缓冲');
    expect(status.textContent).toContain('本次启动设置：分段播放');
    expect(status.textContent).toContain('当前连接策略：待确认');
    expect(status.textContent).toContain('停止并重新启动');
    fireEvent.click(screen.getByRole('button', {name: /启动设置/}));
    fireEvent.click(screen.getByText('语音', {exact: true}));
    expect((screen.getByLabelText('声音交付方式') as HTMLInputElement).disabled).toBe(true);
    expect(request.mock.calls.every(call => call[0] === 'status')).toBe(true);
  });

  test('维护覆盖与连接内回退可见，但不声称播放验收或后台模型已空闲', async () => {
    const value: LauncherSnapshot = {...stopped, state: 'ready', settings: {...stopped.settings, voice: true, cosy_delivery_mode: 'adaptive'},
      cosy_delivery: {version: 1, next_start_mode: 'incremental', next_start_source: 'environment', selection_valid: true,
        startup_mode: 'incremental', startup_source: 'environment', restart_required: false,
        observation: {version: 1, state: 'buffered_fallback', effective_mode: 'buffered', failure_code: 'after_handoff',
          last_outcome: 'failed', handoff_started: true, next_segment_allowed: true, restart_required: false, physical_playback_verified: false}}};
    const {api} = fake(value); render(<LauncherApp api={api}/>);
    const status = await screen.findByLabelText('声音交付状态');
    expect(status.textContent).toContain('维护环境覆盖');
    expect(status.textContent).toContain('当前连接策略：缓冲播放');
    expect(status.textContent).toContain('已交付内容不会重播');
    expect(status.textContent).not.toMatch(/验收通过|模型已空闲|播放成功/);
  });

  test('清理未确认显示需重连，禁止把null模式显示为已恢复', async () => {
    const value: LauncherSnapshot = {...stopped, state: 'ready', settings: {...stopped.settings, voice: true},
      cosy_delivery: {version: 1, next_start_mode: 'incremental', next_start_source: 'preference', selection_valid: true,
        startup_mode: 'incremental', startup_source: 'preference', restart_required: true,
        observation: {version: 1, state: 'restart_required', effective_mode: null, failure_code: 'reader_cleanup_unconfirmed',
          next_segment_allowed: false, restart_required: true, physical_playback_verified: false}}};
    const {api} = fake(value); render(<LauncherApp api={api}/>);
    const status = await screen.findByLabelText('声音交付状态');
    expect(status.textContent).toContain('当前连接策略：待确认');
    expect(status.textContent).toContain('重新连接圆屏');
    expect(status.textContent).not.toContain('已恢复');
  });
});

test('独立端口与自动跟踪只有保存时写入，状态读取不触发服务动作', async () => {
  const {api, request} = fake(); render(<LauncherApp api={api}/>);
  fireEvent.click(await screen.findByRole('button', {name: /启动设置/}));
  fireEvent.change(await screen.findByLabelText('圆屏语音端口'), {target: {value: '18000'}});
  fireEvent.change(screen.getByLabelText('圆屏 OTA 端口'), {target: {value: '18003'}});
  fireEvent.click(screen.getByLabelText('自动跟踪电脑 IP'));
  expect(request.mock.calls.every(([path]) => path === 'status')).toBe(true);
  fireEvent.click(screen.getByRole('button', {name: '保存设置'}));
  await waitFor(() => expect(request).toHaveBeenCalledWith('settings', {
    settings: {voice_ws_port: 18000, voice_http_port: 18003, network_auto: true}, expected_revision: 'rev-1',
  }));
  expect(request.mock.calls.some(([path]) => path === 'actions')).toBe(false);
});

test('网络变化等待状态可见，不把电脑地址同步当作设备重连', async () => {
  const {api, request} = fake({...stopped, settings: {...stopped.settings, network_auto: true},
    network: {state: 'network_waiting', message: '设备仍连接，等待安全窗口；圆屏地址需单独核对。', address: '192.168.1.4'}});
  render(<LauncherApp api={api}/>);
  expect(await screen.findByText('圆屏网络自动跟踪')).toBeTruthy();
  expect(screen.getByText(/圆屏地址需单独核对/)).toBeTruthy();
  expect(request.mock.calls.every(([path]) => path === 'status')).toBe(true);
});
describe('React 启动面板', () => {
  test('设置分类保留草稿，分类与光效开关不会写启动配置', async () => {
    const {api, request} = fake(); render(<LauncherApp api={api}/>);
    fireEvent.click(screen.getByRole('button', {name: '持续光效'}));
    fireEvent.click(await screen.findByRole('button', {name: /启动设置/}));
    fireEvent.change(await screen.findByLabelText('电脑局域网 IP'), {target: {value: '192.168.1.22'}});
    fireEvent.click(screen.getByText('记忆', {exact: true}));
    expect(screen.getByLabelText('记忆召回')).toBeTruthy();
    expect(screen.queryByLabelText('电脑局域网 IP')).toBeNull();
    fireEvent.click(screen.getByText('语音', {exact: true}));
    expect(screen.getByLabelText('聆听环境')).toBeTruthy();
    fireEvent.click(screen.getByText('常用', {exact: true}));
    expect((screen.getByLabelText('电脑局域网 IP') as HTMLInputElement).value).toBe('192.168.1.22');
    expect(request.mock.calls.every(call => call[0] === 'status')).toBe(true);
    fireEvent.click(screen.getByRole('button', {name: '保存设置'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('settings', {settings: {lan_ip: '192.168.1.22'}, expected_revision: 'rev-1'}));
  });
  test('状态核心只消费服务事实，未知和异常没有处理中波形', async () => {
    const {api} = fake({...stopped, state: 'failed'});
    const {container} = render(<LauncherApp api={api}/>);
    expect(container.querySelector('.state-core')?.getAttribute('data-state')).toBe('unknown');
    expect(container.querySelector('.core-pulse')).toBeNull();
    await waitFor(() => expect(container.querySelector('.state-core')?.getAttribute('data-state')).toBe('failed'));
    expect(container.querySelector('.core-pulse')).toBeNull();
  });
  test('打开与卸载只有读操作，未知服务状态不冒充就绪', async () => {
    const {api, request} = fake();
    const {unmount} = render(<LauncherApp api={api}/>);
    expect(await screen.findByRole('button', {name: '开启陪伴'})).toBeTruthy();
    await waitFor(() => expect(screen.getByText('尚未启动')).toBeTruthy());
    expect(screen.getByText('尚未启动').className).toContain('tone-quiet');
    expect(request.mock.calls.every(call => call[0] === 'status')).toBe(true);
    unmount(); expect(request.mock.calls.some(call => call[0] === 'actions')).toBe(false);
  });
  test('只有明确点击才保存交流模式', async () => {
    const {api, request} = fake(); render(<LauncherApp api={api}/>);
    const button = await screen.findByRole('button', {name: /圆屏陪伴/});
    await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false)); fireEvent.click(button);
    await waitFor(() => expect(request).toHaveBeenCalledWith('settings', {settings: {voice: true}, expected_revision: 'rev-1'}));
  });
  test('启动后显示真实 starting 状态并禁止重复操作', async () => {
    const {api, request} = fake(); render(<LauncherApp api={api}/>);
    const start = await screen.findByRole('button', {name: '开启陪伴'});
    await waitFor(() => expect(start.hasAttribute('disabled')).toBe(false));
    request.mockResolvedValue({...stopped, state: 'starting', can_start: false});
    fireEvent.click(start);
    await waitFor(() => expect(screen.getAllByText('正在连接').length).toBeGreaterThan(0));
    expect(screen.getByRole('button', {name: /开启陪伴/}).hasAttribute('disabled')).toBe(true);
  });
  test('停止必须确认，取消不发送停止命令', async () => {
    const {api, request} = fake({...stopped, state: 'ready', can_start: false, can_stop: true, console_url: 'http://127.0.0.1:8765/chat-react'});
    render(<LauncherApp api={api}/>);
    const stop = await screen.findByRole('button', {name: '停止服务'});
    fireEvent.click(stop); expect(await screen.findByText('停止陪伴服务？')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: '继续运行'}));
    expect(request.mock.calls.some(call => call[0] === 'actions')).toBe(false);
    fireEvent.click(stop); const buttons = screen.getAllByRole('button', {name: '停止服务'});
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(request).toHaveBeenCalledWith('actions', {action: 'stop'}));
  });
  test('退出面板确认后只发送一次明确的 shutdown', async () => {
    const {api, request} = fake(); render(<LauncherApp api={api}/>);
    fireEvent.click(await screen.findByRole('button', {name: '停止服务并退出面板'}));
    expect(await screen.findByText('停止服务并退出面板？')).toBeTruthy();
    request.mockResolvedValue({...stopped, shutdown_complete: true});
    fireEvent.click(screen.getByRole('button', {name: '停止并退出'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('actions', {action: 'shutdown'}));
    expect(await screen.findByText('面板已退出')).toBeTruthy();
  });
  test('退出仅排队时不冒充完成，停止失败后恢复错误状态', async () => {
    const {api, request} = fake(); render(<LauncherApp api={api} pollMs={40}/>);
    fireEvent.click(await screen.findByRole('button', {name: '停止服务并退出面板'}));
    request.mockResolvedValue({...stopped, state: 'stopping', can_start: false});
    fireEvent.click(screen.getByRole('button', {name: '停止并退出'}));
    expect(await screen.findByText('正在停止并退出')).toBeTruthy();
    expect(screen.queryByText('面板已退出')).toBeNull();
    request.mockResolvedValue({...stopped, state: 'failed', message: '停止未完成'});
    expect(await screen.findByText('停止未完成')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', {name: '重新启动'}).hasAttribute('disabled')).toBe(false));
  });
  test('打开设置不会自动保存，冲突保留草稿并提示重新载入', async () => {
    const {api, request} = fake(); render(<LauncherApp api={api}/>);
    fireEvent.click(await screen.findByRole('button', {name: /启动设置/}));
    expect(await screen.findByLabelText('电脑局域网 IP')).toBeTruthy();
    expect(request.mock.calls.some(call => call[0] === 'settings')).toBe(false);
    fireEvent.change(screen.getByLabelText('电脑局域网 IP'), {target: {value: '192.168.1.2'}});
    request.mockRejectedValueOnce(new LauncherError(409, '设置已被其他页面修改，请刷新后重新编辑。'));
    fireEvent.click(screen.getByRole('button', {name: '保存设置'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('settings', {settings: {lan_ip: '192.168.1.2'}, expected_revision: 'rev-1'}));
    expect(await screen.findByRole('button', {name: '载入最新设置'})).toBeTruthy();
    expect((screen.getByLabelText('电脑局域网 IP') as HTMLInputElement).value).toBe('192.168.1.2');
  });
  test('停止失败但仍有受管进程时提供确认后的重试停止', async () => {
    const {api, request} = fake({...stopped, state: 'failed', can_start: false, can_stop: true});
    render(<LauncherApp api={api}/>);
    fireEvent.click(await screen.findByRole('button', {name: '重试停止'}));
    expect(await screen.findByText('停止陪伴服务？')).toBeTruthy();
    expect(request.mock.calls.some(call => call[0] === 'actions')).toBe(false);
    fireEvent.click(screen.getByRole('button', {name: '停止服务'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('actions', {action: 'stop'}));
  });
  test('请求失败有可操作提示，不自动重试启动', async () => {
    const {api, request} = fake(); request.mockRejectedValue(new Error('private path'));
    render(<LauncherApp api={api}/>);
    expect(await screen.findByText('无法连接启动面板，请重新打开启动入口。')).toBeTruthy();
    expect(screen.queryByText('private path')).toBeNull();
    expect(request.mock.calls.every(call => call[0] === 'status')).toBe(true);
  });
});
