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
    });
    const client = createConsoleQueryClient();
    const api = new ChatApi();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={api} ready={true}/></QueryClientProvider>);
    expect(await screen.findByText('主动交流当前关闭')).toBeTruthy();
    expect(screen.getByText(/打开开关只保存许可边界/)).toBeTruthy();
    const toggle = screen.getByRole('switch', {name:'允许主动联系'});
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole('button', {name:'保存主动交流设置'}).hasAttribute('disabled')).toBe(false));
    expect(request).toHaveBeenCalledWith('/api/proactive-policy');
    view.unmount(); client.clear();
  });

  test('显式点击才发送一次且页面不把排队说成已播放', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request')
      .mockResolvedValueOnce({
        subject_id:'user:self', enabled:true, utc_offset_minutes:480,
        allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
        daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
        quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:3, updated_at:null,
      })
      .mockResolvedValueOnce({
        outreach_id:'outreach-1', state:'queued', revision:2, replayed:false,
        policy_action:'allow', policy_reason:'ready', delivery_reason:'xiaozhi_queue_accepted',
        device:{ready:true, user_session_active:false, reason:null},
      });
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('6a4db801-6779-40fc-90b4-aab77f580c82');
    const client = createConsoleQueryClient();
    const api = new ChatApi();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={api} ready={true}/></QueryClientProvider>);
    const button = await screen.findByRole('button', {name:'发送一次测试问候'});
    expect(button.hasAttribute('disabled')).toBe(false);
    expect(request).toHaveBeenCalledTimes(1);
    fireEvent.click(button);
    expect(await screen.findByText(/小智服务已接收并排队/)).toBeTruthy();
    expect(screen.getByText(/不能确认圆屏已经播放/)).toBeTruthy();
    expect(request).toHaveBeenLastCalledWith('/api/proactive-outreach/test', 'POST', {
      text:'今天也要照顾好自己呀。',
      request_id:'6a4db801-6779-40fc-90b4-aab77f580c82',
      expected_policy_revision:3,
    });
    expect(request).toHaveBeenCalledTimes(2);
    view.unmount(); client.clear();
  });
});
