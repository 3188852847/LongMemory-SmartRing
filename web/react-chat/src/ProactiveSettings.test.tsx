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
    expect(screen.getByText(/后台触发和圆屏投递尚未接入|本页只保存许可边界/)).toBeTruthy();
    const toggle = screen.getByRole('switch', {name:'允许主动联系'});
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole('button', {name:'保存主动交流设置'}).hasAttribute('disabled')).toBe(false));
    expect(request).toHaveBeenCalledWith('/api/proactive-policy');
    view.unmount(); client.clear();
  });
});
