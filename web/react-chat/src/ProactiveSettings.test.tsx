import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from './api';
import {ProactiveSettings} from './ProactiveSettings';
import {createConsoleQueryClient} from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('主动交流设置', () => {
  test('默认关闭并明确保存不等于后台投递', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      subject_id:'user:self', enabled:false, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:0, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
    });
    const client = createConsoleQueryClient();
    const api = new ChatApi();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={api} ready={true}/></QueryClientProvider>);
    expect(await screen.findByText('主动交流当前关闭')).toBeTruthy();
    expect(screen.getByText(/当天已经聊过/)).toBeTruthy();
    const toggle = screen.getByRole('switch', {name:'允许主动联系'});
    fireEvent.click(toggle);
    const automatic = screen.getByRole('switch', {name:'后台定时问候'});
    await waitFor(() => expect(automatic.hasAttribute('disabled')).toBe(false));
    fireEvent.click(automatic);
    await waitFor(() => expect(screen.getByRole('button', {name:'保存主动交流设置'}).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', {name:'保存主动交流设置'}));
    expect(request).toHaveBeenCalledWith('/api/proactive-policy');
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/api/proactive-policy', 'PUT', expect.objectContaining({
        expected_revision:0, enabled:true, automatic_enabled:true,
        scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
      }),
    ));
    view.unmount(); client.clear();
  });

  test('显式点击才发送一次且页面不把排队说成已播放', async () => {
    const policy = {
        subject_id:'user:self', enabled:true, utc_offset_minutes:480,
        allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
        daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
        quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:3, updated_at:null,
        automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
      };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/proactive-policy') return policy;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path === '/api/proactive-outreach/test') return {
        outreach_id:'outreach-1', state:'queued', revision:2, replayed:false,
        policy_action:'allow', policy_reason:'ready', delivery_reason:'xiaozhi_queue_accepted',
        device:{ready:true, user_session_active:false, reason:null},
      };
      throw new Error(`unexpected path: ${path}`);
    });
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('6a4db801-6779-40fc-90b4-aab77f580c82');
    const client = createConsoleQueryClient();
    const api = new ChatApi();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={api} ready={true}/></QueryClientProvider>);
    const button = await screen.findByRole('button', {name:'发送一次测试问候'});
    expect(button.hasAttribute('disabled')).toBe(false);
    fireEvent.click(button);
    expect(await screen.findByText(/小智服务已接收并排队/)).toBeTruthy();
    expect(screen.getByText(/不能确认圆屏已经播放/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith('/api/proactive-outreach/test', 'POST', {
      text:'今天也要照顾好自己呀。',
      request_id:'6a4db801-6779-40fc-90b4-aab77f580c82',
      expected_policy_revision:3,
    });
    expect(request.mock.calls.filter(([path]) => path === '/api/proactive-outreach/test')).toHaveLength(1);
    view.unmount(); client.clear();
  });

  test('只有用户点击确认才把排队记录推进为已播放', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:3, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
    };
    const queued = {
      outreach_id:'a'.repeat(32), trigger:'manual_test', content:'合成问候',
      created_at:'2026-09-07T04:00:00+00:00', expires_at:'2026-09-07T04:05:00+00:00',
      state:'queued', revision:2, reason:'ready', event_count:2, failure_reason:null,
    };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/proactive-policy') return policy;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[queued]};
      if (path.endsWith('/confirm-played')) return {
        outreach_id:queued.outreach_id, state:'played', revision:3, replayed:false,
        policy_action:null, policy_reason:null, delivery_reason:null, device:null,
      };
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    fireEvent.click(await screen.findByRole('button', {name:'确认已听到'}));
    expect(await screen.findByText(/亲耳观察记录为 played/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith(
      `/api/proactive-outreach/${queued.outreach_id}/confirm-played`,
      'POST', {expected_revision:2},
    );
    expect(request.mock.calls.filter(([path]) => String(path).endsWith('/confirm-played'))).toHaveLength(1);
    view.unmount(); client.clear();
  });

  test('话题素材必须由用户写明可播短句且保存本身不会投递', async () => {
    const policy = {
      subject_id:'user:self', enabled:false, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v2', revision:0, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
    };
    const scenario = {id:'scenario-1',title:'毕业设计',summary:'用户正在准备毕业设计汇报。',revision:2};
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method) => {
      if (path === '/api/proactive-policy') return policy;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path.startsWith('/api/scenarios?')) return {items:[scenario]};
      if (path === '/api/proactive-topic-seeds' && method === 'POST') return {
        id:'a'.repeat(32), subject_id:'user:self', scenario_id:scenario.id,
        prompt_text:'毕业设计准备得怎么样了？', status:'active', revision:1,
        created_at:'2026-09-07T06:00:00+00:00', updated_at:'2026-09-07T06:00:00+00:00',
        usable:true, source:{layer:'l2',title:scenario.title,summary:scenario.summary,status:'active'},
      };
      if (path === '/api/proactive-topic-seeds') return {items:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('6a4db801-6779-40fc-90b4-aab77f580c82');
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    fireEvent.mouseDown(await screen.findByLabelText('来源 L2 场景'));
    fireEvent.click(await screen.findByText('毕业设计'));
    fireEvent.change(screen.getByLabelText('允许播出的安全话题'), {target:{value:'毕业设计准备得怎么样了？'}});
    fireEvent.click(screen.getByRole('button', {name:'保存为话题素材'}));
    expect(await screen.findByText(/当前只供预览，不会自动播报/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith('/api/proactive-topic-seeds', 'POST', {
      scenario_id:'scenario-1', expected_scenario_revision:2,
      prompt_text:'毕业设计准备得怎么样了？',
      request_id:'6a4db801-6779-40fc-90b4-aab77f580c82',
    });
    expect(request.mock.calls.some(([path]) => path === '/api/proactive-outreach/test')).toBe(false);
    view.unmount(); client.clear();
  });
});
