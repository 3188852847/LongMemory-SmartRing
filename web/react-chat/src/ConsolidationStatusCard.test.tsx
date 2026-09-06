import {render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {ChatApi} from './api';
import {ConsolidationStatusCard} from './ConsolidationStatusCard';

afterEach(()=>vi.restoreAllMocks());

describe('ConsolidationStatusCard',()=>{
  it('explains that readiness does not mean background execution',async()=>{
    vi.spyOn(ChatApi.prototype,'request').mockResolvedValue({background_enabled:false,stages:[{
      stage:'l1_to_l2',pending_new_source_count:5,trigger_action:'run',trigger_reason:'ready',
      minimum_new_sources:4,maximum_sources_per_run:20,cooldown_seconds:21600,
      daily_model_call_budget:2,model_calls_today:0,remaining_model_calls_today:2,
      cursor:null,latest_run:null,
    }]});
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={client}><ConsolidationStatusCard stage="l1_to_l2" enabled/></QueryClientProvider>);
    await waitFor(()=>expect(screen.getByText('已达到触发门槛')).toBeTruthy());
    expect(screen.getByText('后台尚未启用')).toBeTruthy();
    expect(screen.getByText(/当前不会自动调用模型/)).toBeTruthy();
  });
});
