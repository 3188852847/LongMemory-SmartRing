import {render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {ApiError,ChatApi} from './api';
import {MemoryRouter} from 'react-router-dom';
import {consolidationStatusFailure,ConsolidationOverview,ConsolidationStatusCard} from './ConsolidationStatusCard';

afterEach(()=>vi.restoreAllMocks());

describe('ConsolidationStatusCard',()=>{
  it('does not expose raw status request failures',()=>{
    expect(consolidationStatusFailure(new Error('private database path'))).not.toContain('private database path');
    expect(consolidationStatusFailure(new ApiError('http_404',404))).toContain('没有提供自动整理状态接口');
  });

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

  it('shows both stages in one read-only daily overview',async()=>{
    vi.spyOn(ChatApi.prototype,'request').mockResolvedValue({background_enabled:false,stages:[{
      stage:'l1_to_l2',pending_new_source_count:5,trigger_action:'run',trigger_reason:'ready',
      minimum_new_sources:4,maximum_sources_per_run:20,cooldown_seconds:21600,
      daily_model_call_budget:2,model_calls_today:0,remaining_model_calls_today:2,cursor:null,latest_run:null,
    },{
      stage:'l2_to_l3',pending_new_source_count:1,trigger_action:'hold',trigger_reason:'below_source_threshold',
      minimum_new_sources:3,maximum_sources_per_run:12,cooldown_seconds:86400,
      daily_model_call_budget:1,model_calls_today:0,remaining_model_calls_today:1,cursor:null,latest_run:null,
    }]});
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={client}><MemoryRouter><ConsolidationOverview enabled/></MemoryRouter></QueryClientProvider>);
    await waitFor(()=>expect(screen.getByText('已达到触发门槛')).toBeTruthy());
    expect(screen.getByRole('region',{name:'L1 → L2 场景整理'})).toBeTruthy();
    expect(screen.getByRole('region',{name:'L2 → L3 画像整理'})).toBeTruthy();
    expect(screen.getByText('新来源尚未达到门槛')).toBeTruthy();
    expect(screen.getByText(/不会因为打开页面而调用模型/)).toBeTruthy();
    expect(screen.queryByRole('button',{name:/立即/})).toBeNull();
    expect(screen.getByRole('link',{name:'查看与复核 L2'}).getAttribute('href')).toBe('/scenarios');
  });
});
