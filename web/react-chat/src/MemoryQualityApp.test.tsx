import {afterEach,describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi, type MemoryFeedbackIndex} from './api';
import {MemoryQualityApp} from './MemoryQualityApp';

afterEach(()=>vi.restoreAllMocks());

describe('记忆质量样本工作台',()=>{
  test('默认只呈现问题队列和无正文诊断元数据',async()=>{
    const response:MemoryFeedbackIndex={
      kind:'issues',offset:0,limit:25,total:1,
      counts:{memory_ok:2,recall_miss:1,wrong_memory:0,memory_irrelevant:3},
      items:[{source:'web_chat',chat_id:'chat-a',chat_title:'关于豆包',request_id:'request-a',kind:'recall_miss',revision:1,occurred_at:'2026-09-09T12:00:00Z',retrieved_counts:{l1:0,l2:0,l3:0},diagnostic_focus:'retrieval'}],
    };
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockResolvedValue(response as never);
    render(<MemoryRouter><MemoryQualityApp/></MemoryRouter>);
    expect(await screen.findByText('关于豆包')).toBeTruthy();
    expect(screen.getByText('没有召回 L1/L2/L3，优先核对检索查询和候选覆盖。')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByRole('link',{name:'核对回答与证据'}).getAttribute('href')).toBe('/chat-react?chat_id=chat-a&request_id=request-a');
    expect(screen.queryByText(/用户说过/)).toBeNull();
  });

  test('圆屏反馈使用独立来源标签并跳到用户 L0',async()=>{
    const response:MemoryFeedbackIndex={
      kind:'issues',offset:0,limit:25,total:1,
      counts:{memory_ok:0,recall_miss:0,wrong_memory:1,memory_irrelevant:0},
      items:[{source:'round_screen',chat_id:null,chat_title:'圆屏语音',request_id:'l0-user',feedback_event_id:'event-a',feedback_message_id:'l0-feedback',assistant_message_id:'l0-assistant',kind:'wrong_memory',revision:1,occurred_at:'2026-09-10T01:00:00Z',retrieved_counts:{l1:1,l2:0,l3:0},retrieval_evidence_recorded:true,retrieval_evidence:[{layer:'l1',item_id:'memory-a',rank:1,content_sha256:'a'.repeat(64)}],diagnostic_focus:'memory_content_freshness_subject_or_ranking'}],
    };
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>path.startsWith('/api/round-screen-memory-feedback/')?{
      id:'event-a',event_kind:'wrong_memory',evidence_kind:'explicit_round_screen_statement',interpreter_version:'v1',occurred_at:'2026-09-10T01:00:00Z',target_user_message_id:'l0-user',assistant_message_id:'l0-assistant',feedback_message_id:'l0-feedback',question:'我的猫叫什么？',question_at:'2026-09-10T00:59:00Z',answer:'叫豆包。',answer_at:'2026-09-10T00:59:02Z',feedback:'你刚才记错了。',feedback_at:'2026-09-10T01:00:00Z',retrieval_evidence_recorded:true,retrieval_evidence:[{layer:'l1',item_id:'memory-a',rank:1,content_sha256:'a'.repeat(64),current_content:'用户的猫叫豆包。',current_state:'available',matches_receipt:true}],
    } as never:response as never);
    render(<MemoryRouter><MemoryQualityApp/></MemoryRouter>);
    expect((await screen.findAllByText('圆屏语音')).length).toBe(2);
    expect(screen.getByText('圆屏语音',{selector:'.ant-tag'})).toBeTruthy();
    expect(screen.getByRole('link',{name:'问题 L0'}).getAttribute('href')).toBe('/memories?l0_message_id=l0-user');
    expect(screen.getByRole('link',{name:'回答 L0'}).getAttribute('href')).toBe('/memories?l0_message_id=l0-assistant');
    expect(screen.getByRole('link',{name:'反馈 L0'}).getAttribute('href')).toBe('/memories?l0_message_id=l0-feedback');
    expect(screen.getByRole('link',{name:'L1 #1'}).getAttribute('href')).toBe('/memories?memory_id=memory-a');
    fireEvent.click(screen.getByRole('button',{name:'在此核对'}));
    expect(await screen.findByText('我的猫叫什么？')).toBeTruthy();
    expect(screen.getByText('用户的猫叫豆包。')).toBeTruthy();
    expect(screen.getByText('与回答时一致')).toBeTruthy();
  });
});
