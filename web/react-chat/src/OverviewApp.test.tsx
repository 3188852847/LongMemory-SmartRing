import {describe, expect, test, vi} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from './api';
import {OverviewApp} from './OverviewApp';

describe('系统总览', () => {
  test('只读汇总模型、记忆和当前设备事实', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path: string) => {
      if (path === '/api/chat-config') return {enabled:true,database:'synthetic.db',model:'SyntheticModel',role:'测试角色',provider:'openai_compatible',method:'longmemory_daily_llm_v2',retrieval:'keyword_dense_rrf_v1',model_health:{state:'available',code:null,checked_at:'2026-09-10T00:00:00Z'}};
      if (path === '/api/device') return {connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,read_status_supported:true,set_brightness_supported:true,set_theme_supported:true,aec_advertised:true};
      if (path === '/api/runtime-status') return {enabled:true,state:'ready',reason:null,updated_at:'2026-09-10T00:00:00Z',age_seconds:0.4,services:{console:'ready',voice:'running',voxcpm2:'disabled'}};
      if (path.startsWith('/api/memories?')) return {total:12,limit:1,offset:0,items:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    const query = new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={query}><MemoryRouter><OverviewApp/></MemoryRouter></QueryClientProvider>);

    expect((await screen.findAllByText('SyntheticModel')).length).toBe(2);
    expect(await screen.findByText('12 条')).toBeTruthy();
    expect(screen.getAllByText('已连接').length).toBeGreaterThan(0);
    expect(await screen.findByText('启动面板在线')).toBeTruthy();
    expect(screen.getByText('0.4 秒前')).toBeTruthy();
    expect(screen.getByRole('link', {name:'文字聊天'}).getAttribute('href')).toBe('/chat-react');
    expect(screen.getByRole('link', {name:'打开设备诊断'}).getAttribute('href')).toBe('/device');
  });
});
