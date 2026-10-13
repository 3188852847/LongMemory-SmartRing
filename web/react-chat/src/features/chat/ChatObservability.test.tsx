import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {ConsoleStatusRail, MemoryFeedbackControls, TurnMemoryEvidence, memoryFeedbackDiagnosis, memoryTraceSummary} from './ChatObservability';
import type {Config, Turn} from '../../api';

const config:Config = {enabled:true,database:'synthetic.db',model:'Synthetic-Model',role:'助手',provider:'openai_compatible',method:'longmemory_daily_llm_v2',retrieval:'keyword_dense_rrf_v1',model_health:{state:'available',code:null,checked_at:'2026-09-09T00:00:00Z'}};

describe('ConsoleStatusRail', () => {
  it('只按真实探测值呈现状态和有效记忆数', () => {
    render(<MemoryRouter><ConsoleStatusRail config={config} device={{connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,read_status_supported:true,set_brightness_supported:true,set_theme_supported:true}} deviceFailed={false} activeMemoryCount={128}/></MemoryRouter>);
    expect(screen.getByText('已连接')).toBeTruthy();
    expect(screen.getByText('128 条有效 L1')).toBeTruthy();
    expect(screen.getByText('Synthetic-Model')).toBeTruthy();
    expect(screen.getByText('关键词＋向量')).toBeTruthy();
    expect(screen.getByRole('link',{name:'查看圆屏诊断'}).getAttribute('href')).toBe('/device');
    expect(screen.getByRole('link',{name:'查看模型诊断'}).getAttribute('href')).toBe('/settings?tab=model');
  });

  it('探测失败时不把旧状态冒充在线', () => {
    render(<MemoryRouter><ConsoleStatusRail config={config} device={undefined} deviceFailed activeMemoryCount={undefined}/></MemoryRouter>);
    expect(screen.getByText('状态未知')).toBeTruthy();
    expect(screen.getByText('L1 数量未知')).toBeTruthy();
  });
});

describe('TurnMemoryEvidence', () => {
  it('分层呈现实际召回与写入', () => {
    const turn:Turn = {input:'我的猫叫什么',answer:'豆包',status:'completed',user_saved:true,duration_ms:12,writes:[{operation:'noop',item_id:'l1-a'}],retrieved:[{item_id:'l1-a',content:'用户养了一只叫豆包的猫。',source_event_ids:['l0-a']}],scenario_retrieved:[{scenario_id:'l2-a',title:'养猫',summary:'用户与豆包一起生活。',source_memory_ids:['l1-a'],source_message_ids:['l0-a']}],persona_retrieved:[{persona_id:'l3-a',label:'宠物偏好',statement:'用户喜欢猫。'}]};
    render(<MemoryRouter><TurnMemoryEvidence turn={turn}/></MemoryRouter>);
    expect(screen.getByText('[ MEM HIT ]')).toBeTruthy();
    expect(screen.getByText('回答使用 L1 1 · L2 1 · L3 1')).toBeTruthy();
    expect(screen.getByText('用户养了一只叫豆包的猫。')).toBeTruthy();
    expect(screen.getByText('重复证据')).toBeTruthy();
    expect(screen.getByRole('link', {name:'核对 L0 原话'}).getAttribute('href')).toBe('/memories?memory_id=l1-a');
    expect(screen.getByRole('link', {name:'核对场景依据'}).getAttribute('href')).toBe('/scenarios?scenario_id=l2-a');
    expect(screen.getByRole('link', {name:'核对画像依据'}).getAttribute('href')).toBe('/personas?persona_id=l3-a');
  });

  it('无召回只陈述本轮事实，不声称用户从未说过', () => {
    const turn:Turn = {input:'问题',answer:'不知道',status:'completed',user_saved:true,duration_ms:2,writes:[],retrieved:[]};
    expect(memoryTraceSummary(turn).code).toBe('NO RECALL');
    render(<MemoryRouter><TurnMemoryEvidence turn={turn}/></MemoryRouter>);
    expect(screen.getByText('本轮没有召回长期记忆；不等于用户从未说过')).toBeTruthy();
  });

  it('把退役变化链证据明确标为历史事实', () => {
    const turn:Turn = {input:'我以前住在哪里',answer:'南京',status:'completed',user_saved:true,duration_ms:2,writes:[],retrieved:[
      {item_id:'current',content:'用户住在合肥。',source_event_ids:['source-current']},
      {item_id:'old',content:'用户住在南京。',source_event_ids:['source-old'],temporal_role:'historical',valid_from:null,valid_to:'2026-05-01T00:00:00+00:00'},
    ]};
    render(<MemoryRouter><TurnMemoryEvidence turn={turn}/></MemoryRouter>);
    expect(screen.getByText('历史事实')).toBeTruthy();
    expect(screen.getByText(/结束.*2026/)).toBeTruthy();
    expect(screen.getByText('用户住在南京。')).toBeTruthy();
  });
});

describe('MemoryFeedbackControls', () => {
  it('显示当前人工复核并允许改标，但不声称会自动修改记忆', () => {
    const selected:string[] = [];
    const turn:Turn = {request_id:'550e8400-e29b-41d4-a716-446655440000',input:'我的猫叫什么',answer:'豆包',status:'completed',user_saved:true,duration_ms:12,writes:[],retrieved:[],memory_feedback:{kind:'memory_ok',revision:2,occurred_at:'2026-09-09T10:00:00Z'}};
    render(<MemoryFeedbackControls turn={turn} disabled={false} onSelect={kind=>selected.push(kind)}/>);
    expect(screen.getByRole('button',{name:'记忆使用正常'}).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('已复核 · 修订 2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'没想起已有记忆'}));
    expect(selected).toEqual(['recall_miss']);
  });

  it('依据可见轨迹给排查方向而不冒充根因', () => {
    const base:Turn = {request_id:'550e8400-e29b-41d4-a716-446655440000',input:'问题',answer:'回答',status:'completed',user_saved:true,duration_ms:1,writes:[],retrieved:[]};
    expect(memoryFeedbackDiagnosis({...base,memory_feedback:{kind:'recall_miss',revision:1,occurred_at:'2026-09-09T10:00:00Z'}})).toContain('优先核对检索');
    expect(memoryFeedbackDiagnosis({...base,retrieved:[{item_id:'l1-a',content:'证据'}],memory_feedback:{kind:'recall_miss',revision:1,occurred_at:'2026-09-09T10:00:00Z'}})).toContain('回答是否采用');
    expect(memoryFeedbackDiagnosis({...base,memory_feedback:{kind:'wrong_memory',revision:1,occurred_at:'2026-09-09T10:00:00Z'}})).toContain('不要直接归因');
  });
});
