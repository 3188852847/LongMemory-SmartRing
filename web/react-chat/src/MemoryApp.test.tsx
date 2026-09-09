import {afterEach,describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from './api';
import {MemoryApp} from './MemoryApp';

afterEach(()=>vi.restoreAllMocks());

describe('每日记忆回顾',()=>{
  test('从当天回顾直达已有的追加式纠正确认窗',async()=>{
    const item={id:'memory-1',content:'用户喜欢乌龙茶。',truncated:false,state:'active' as const,activity:'added' as const,
      recorded_at:'2026-09-09T08:00:00+00:00',subject_id:'user:self'};
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{
      if(path==='/api/memory-config') return {configured:true,database:'synthetic.db',allow_delete:true,allow_correction:true,allow_change:true} as never;
      if(path==='/api/memory-mode') return {write_enabled:true,use_enabled:true,scenario_use_enabled:false,scenario_available:true,persona_use_enabled:false,persona_available:true,persistent:false,l0_archived_when_write_disabled:true} as never;
      if(path==='/api/consolidation-status') return {background_enabled:false,stages:[]} as never;
      if(path.startsWith('/api/memories/daily-review')) return {local_date:'2026-09-09',utc_offset_minutes:480,items:[item],total:1,limited:false,activity_counts:{added:1,corrected:0,changed:0,deleted:1},message_counts:{user:3,assistant:3,total:6,unlinked_user:1},deletions:[{id:'deletion-1',memory_id:'deleted-memory-1',subject_id:'user:self',deleted_at:'2026-09-09T09:00:00+00:00'}],deletions_limited:false} as never;
      if(path.startsWith('/api/source-messages?')) return {items:[{id:'source-unlinked',role:'user',content:'我最近开始晨跑。',truncated:false,created_at:'2026-09-09T07:00:00+00:00',linked_memory_count:0}],total:1,limit:25,offset:0} as never;
      if(path==='/api/memories/memory-1') return {...item,revision:'a'.repeat(64),valid_from:null,valid_to:null,retired_at:null,superseded_by_id:null,sources:[]} as never;
      if(path.startsWith('/api/memories?')) return {items:[item],total:1,limit:25,offset:0} as never;
      throw new Error(`unexpected test path: ${path}`);
    });

    const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={client}><MemoryRouter><MemoryApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText(/每日记忆回顾/)).toBeTruthy();
    expect((await screen.findAllByText('用户喜欢乌龙茶。')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('新增 1')).toBeTruthy();
    expect(screen.getByText(/当天归档 L0：用户 3 条，助手 3 条/)).toBeTruthy();
    expect(screen.getByText(/其中 1 条用户原话没有形成 L1/)).toBeTruthy();
    expect(screen.getByText('删除 1')).toBeTruthy();
    fireEvent.click(screen.getByText(/查看删除审计/));
    expect(screen.getByText('deleted-memory-1')).toBeTruthy();
    expect(screen.getByText(/不保留被删正文/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'核对当天未形成 L1 的原话'}));
    await waitFor(()=>expect(screen.getByText('我最近开始晨跑。')).toBeTruthy());
    expect(screen.getByLabelText('L0 日期').getAttribute('value')).toBe('2026-09-09');
    fireEvent.click(screen.getByText('L1 原子记忆 · 1'));
    const correctionButton=screen.getByRole('button',{name:'直接纠正'});
    await waitFor(()=>expect(correctionButton.hasAttribute('disabled')).toBe(false));
    fireEvent.click(correctionButton);
    expect(await screen.findByText('纠正 L1')).toBeTruthy();
    expect(screen.getByText(/新建 L1，并保留旧记录/)).toBeTruthy();
  });
});
