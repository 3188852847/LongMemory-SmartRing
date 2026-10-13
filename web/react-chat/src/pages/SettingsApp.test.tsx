import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, test, vi} from 'vitest';
import {MemoryRouter, useNavigate} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {SettingsApp} from './SettingsApp';
import {AppearanceProvider} from '../app/AppearanceProvider';
import {createConsoleQueryClient} from '../app/queryClient';
import {ChatApi} from '../api';

function HistoryControls() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate(-1)}>测试后退</button><button onClick={() => navigate(1)}>测试前进</button></>;
}
function mount(path='/settings') {
  vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
  vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
    if (path === '/api/chat-config') return {enabled:true, role:'合成助手', model:'fake', provider:'fake'};
    if (path === '/api/voice-profile') return {profile:{version:1, reference_id:null, transcript:'', style:''}, references:[], profile_digest:'a'.repeat(64), preview_text:'合成试听文本', service_state:'ready', activation:'next_synthesis'};
    if (path === '/api/assistant-role') return {current:{revision:1,name:'合成助手',prompt:'合成角色',saved_at:null}, web:'next_turn',device:'not_synced'};
    if (path === '/api/round-skins') return {enabled:true, selected_skin:'test',skins:[]};
    if (path === '/api/tts-backends') return {enabled:true, next_start_backend:'cosyvoice3'};
    if (path === '/api/proactive-policy') return {enabled:false};
    throw new Error(`没有配置合成响应：${path}`);
  });
  render(<QueryClientProvider client={createConsoleQueryClient()}><AppearanceProvider>
    <MemoryRouter initialEntries={[path]}><SettingsApp/><HistoryControls/></MemoryRouter>
  </AppearanceProvider></QueryClientProvider>);
}
afterEach(() => vi.restoreAllMocks());

describe('设置任务工作区', () => {
  test('分类直接可达，总览单独进入，前进后退恢复分类', async () => {
    mount();
    for (const name of ['设置总览','模型与服务','记忆后端','助手表达','声音与克隆','外观与阅读','主动交流']) {
      expect(screen.getByRole('tab', {name, exact:true})).toBeTruthy();
    }
    expect(screen.queryByRole('region', {name:'当前设置摘要'})).toBeNull();
    fireEvent.click(screen.getByRole('tab', {name:'外观与阅读'}));
    expect(screen.getByRole('combobox', {name:'主题'})).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name:'测试后退'}));
    await waitFor(() => expect(screen.getByRole('tab', {name:'助手表达'}).getAttribute('aria-selected')).toBe('true'));
    fireEvent.click(screen.getByRole('button', {name:'测试前进'}));
    await waitFor(() => expect(screen.getByRole('tab', {name:'外观与阅读'}).getAttribute('aria-selected')).toBe('true'));
    fireEvent.click(screen.getByRole('tab', {name:'设置总览'}));
    expect(await screen.findByRole('region', {name:'当前设置摘要'})).toBeTruthy();
  });

  test('声音草稿跨分类保留，声音引擎与判停按任务进入', async () => {
    mount('/settings?tab=voice');
    await screen.findByText('固定试听文本：合成试听文本');
    expect(screen.queryByRole('heading', {name:'拾音灵敏度'})).toBeNull();
    expect(screen.queryByRole('heading', {name:'圆屏声音后端'})).toBeNull();
    fireEvent.change(screen.getByLabelText('表达指令（可留空）'), {target:{value:'合成语气'}});
    fireEvent.click(screen.getByRole('tab', {name:'助手表达'}));
    fireEvent.click(screen.getByRole('tab', {name:'声音与克隆',exact:true}));
    expect((screen.getByLabelText('表达指令（可留空）') as HTMLInputElement).value).toBe('合成语气');
    expect(screen.getByText(/有未保存的声音草稿/)).toBeTruthy();
    expect(screen.getByRole('list', {name:'声音设置流程'})).toBeTruthy();
  });
});
