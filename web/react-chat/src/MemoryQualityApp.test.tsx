import {afterEach,describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi, type L1ExtractionAuditPage, type L1SufficiencyShadowDetail, type L1SufficiencyShadowPage, type L2SufficiencyShadowDetail, type L2SufficiencyShadowPage, type MemoryFeedbackIndex} from './api';
import {MemoryQualityApp} from './MemoryQualityApp';

afterEach(()=>vi.restoreAllMocks());

describe('记忆质量样本工作台',()=>{
  test('只为最新失败项提供单次重新提取入口',async()=>{
    const feedback:MemoryFeedbackIndex={kind:'issues',offset:0,limit:25,total:0,counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},review_counts:{open:0,resolved:0,dismissed:0},items:[]};
    const attempt='11111111-1111-4111-8111-111111111111';
    const audit:L1ExtractionAuditPage={limit:30,counts:{noop:0,added:0,reused:0,extraction_failed:1,persistence_failed:0,incomplete:0},items:[{attempt_id:attempt,source_message_id:'source-failed',started_at:'2026-09-13T01:00:00Z',finished_at:'2026-09-13T01:00:01Z',method_version:'1',prompt_version:'candidate-v1',preprocessor_version:'safety-v3',prompt_sha256:'a'.repeat(64),provider:'official',model:'model-a',phase:'failed',outcome_code:'extraction_failed',candidate_count:0,added_count:0,duration_ms:1000,retryable:true}]};
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async (path,method)=>{
      if(path==='/api/l1-extraction-audit?limit=30')return audit as never;
      if(method==='POST')return {state:'queued'} as never;
      return feedback as never;
    });
    render(<MemoryRouter><MemoryQualityApp/></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button',{name:'重新提取一次'}));
    await waitFor(()=>expect(request).toHaveBeenCalledWith(
      '/api/l1-extraction-audit/source-failed/retry','POST',
      {expected_attempt_id:attempt},
    ));
    expect(await screen.findByText(/已排队重新提取一次/)).toBeTruthy();
  });

  test('默认只呈现问题队列和无正文诊断元数据',async()=>{
    const response:MemoryFeedbackIndex={
      kind:'issues',offset:0,limit:25,total:1,
      counts:{memory_ok:2,recall_miss:1,wrong_memory:0,memory_irrelevant:3},
      review_counts:{open:1,resolved:0,dismissed:0},
      items:[{source:'web_chat',chat_id:'chat-a',chat_title:'关于豆包',request_id:'request-a',feedback_target_id:'request-a',kind:'recall_miss',revision:1,occurred_at:'2026-09-09T12:00:00Z',retrieved_counts:{l1:0,l2:0,l3:0},diagnostic_focus:'retrieval',review:{state:'open',reason_code:null,review_revision:0,occurred_at:null}}],
    };
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const request=vi.spyOn(ChatApi.prototype,'request').mockResolvedValue(response as never);
    render(<MemoryRouter><MemoryQualityApp/></MemoryRouter>);
    expect(await screen.findByText('关于豆包')).toBeTruthy();
    expect(screen.getByText('没有召回 L1/L2/L3，优先核对检索查询和候选覆盖。')).toBeTruthy();
    expect(screen.getByText('待处理')).toBeTruthy();
    expect(screen.getByRole('link',{name:'核对回答与证据'}).getAttribute('href')).toBe('/chat-react?chat_id=chat-a&request_id=request-a');
    expect(screen.queryByText(/用户说过/)).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'标为已处理'}));
    expect(screen.getByText('这只管理诊断队列，不会自动修改、删除或重新生成长期记忆。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'保存复核状态'}));
    await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/chat-memory-feedback/reviews','POST',{
      source:'web_chat',target_id:'request-a',feedback_revision:1,action:'resolve',
      reason_code:'memory_corrected',expected_review_revision:0,
    }));
  });

  test('圆屏反馈使用独立来源标签并跳到用户 L0',async()=>{
    const response:MemoryFeedbackIndex={
      kind:'issues',offset:0,limit:25,total:1,
      counts:{memory_ok:0,recall_miss:0,wrong_memory:1,memory_irrelevant:0},
      review_counts:{open:1,resolved:0,dismissed:0},
      items:[{source:'round_screen',chat_id:null,chat_title:'圆屏语音',request_id:'l0-user',feedback_target_id:'event-a',feedback_event_id:'event-a',feedback_message_id:'l0-feedback',assistant_message_id:'l0-assistant',kind:'wrong_memory',revision:1,occurred_at:'2026-09-10T01:00:00Z',retrieved_counts:{l1:1,l2:0,l3:0},retrieval_evidence_recorded:true,retrieval_evidence:[{layer:'l1',item_id:'memory-a',rank:1,content_sha256:'a'.repeat(64)}],diagnostic_focus:'memory_content_freshness_subject_or_ranking',review:{state:'open',reason_code:null,review_revision:0,occurred_at:null}}],
    };
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>path.startsWith('/api/round-screen-memory-feedback/')?{
      id:'event-a',event_kind:'wrong_memory',evidence_kind:'explicit_round_screen_statement',interpreter_version:'v1',occurred_at:'2026-09-10T01:00:00Z',target_user_message_id:'l0-user',assistant_message_id:'l0-assistant',feedback_message_id:'l0-feedback',question:'我的猫叫什么？',question_at:'2026-09-10T00:59:00Z',answer:'叫豆包。',answer_at:'2026-09-10T00:59:02Z',feedback:'你刚才记错了。',feedback_at:'2026-09-10T01:00:00Z',retrieval_strategy:'keyword_dense_rrf_v1',retrieval_evidence_recorded:true,retrieval_evidence:[{layer:'l1',item_id:'memory-a',rank:1,content_sha256:'a'.repeat(64),keyword_score:1,dense_score:0.8123,fused_score:0.0314,current_content:'用户的猫叫豆包。',current_state:'available',matches_receipt:true}],
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
    expect(screen.getByText('keyword_dense_rrf_v1')).toBeTruthy();
    expect(screen.getByText(/关键词 1 · 余弦 0.812 · 融合 0.0314/)).toBeTruthy();
  });

  test('L2影子记录明确不生效并可核对候选判断',async()=>{
    const feedback:MemoryFeedbackIndex={
      kind:'issues',offset:0,limit:25,total:0,
      counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},
      review_counts:{open:0,resolved:0,dismissed:0},items:[],
    };
    const shadow:L2SufficiencyShadowPage={
      limit:20,runtime:{enabled:true,state:'completed'},review_counts:{completed:1,unreviewed:1,correct:0,incorrect:0,uncertain:0},policy_metrics:{reviewed_cases:0,labeled_cases:0,answerable_labeled_cases:0,unsupported_labeled_cases:0,excluded_latest_reviews:0,false_block_cases:0,unsupported_pass_cases:0,incomplete_allow_cases:0,overinclusive_allow_cases:0,original_candidate_count:0,kept_candidate_count:0,removed_candidate_count:0,candidate_reduction_rate:null,context_measured_cases:0,original_context_characters:0,kept_context_characters:0,context_character_reduction_rate:null,candidate_precision:null,candidate_recall:null,readiness:{policy_id:'l2-sufficiency-controlled-trial-readiness-v1',status:'not_ready',automatic_activation:false,minimum_cases_per_stratum:60,confidence_level:0.95,answerable_zero_error_upper_bound:null,unsupported_zero_error_upper_bound:null,conditions:[{code:'answerable_sample_floor',passed:false,actual:0,required:60}],limitations:[]}},items:[{
        user_message_id:'turn-shadow',query:'我的猫是什么颜色',
        retrieval_strategy:'l2_keyword_v1',reviewer_version:'gate-v2',
        provider:'openai_compatible',model:'deepseek-v4-flash',status:'completed',
        requested_at:'2026-09-13T01:00:00Z',completed_at:'2026-09-13T01:00:01Z',
        error_code:null,candidate_count:1,supported_count:0,review_verdict:null,
        review_revision:null,
      }],
    };
    const detail:L2SufficiencyShadowDetail={
      ...shadow.items[0],prompt_sha256:'a'.repeat(64),candidates:[{
        scenario_id:'scene-cat',rank:1,content_sha256:'b'.repeat(64),content_characters:20,keyword_score:2,
        supports_answer:0,reason_code:'missing_attribute',current_title:'猫咪',
        current_summary:'用户养了一只叫豆包的猫。',current_status:'active',
        content_matches_snapshot:true,
      }],review:{verdict:null,reason_code:null,review_revision:0,occurred_at:null,expected_supported_scenario_ids:null},
    };
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{
      if(path==='/api/l2-sufficiency-shadow?limit=20')return shadow as never;
      if(path==='/api/l2-sufficiency-shadow/turn-shadow')return detail as never;
      return feedback as never;
    });
    render(<MemoryRouter><MemoryQualityApp/></MemoryRouter>);
    expect(await screen.findByText('我的猫是什么颜色')).toBeTruthy();
    expect(screen.getByText('这里只显示‘如果门控生效会怎样’')).toBeTruthy();
    expect(screen.getByText('正式 L2 门控未就绪')).toBeTruthy();
    expect(screen.getAllByText(/有支持证据 0\/60/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/有证据问题样本：当前 0，要求 60/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button',{name:'查看候选判断'}));
    expect(await screen.findByText('证据不足')).toBeTruthy();
    expect(screen.getByText('missing_attribute')).toBeTruthy();
    expect(screen.getByRole('link',{name:'打开 L2'}).getAttribute('href')).toBe('/scenarios?scenario_id=scene-cat');
    fireEvent.click(screen.getByRole('button',{name:'判断错误'}));
    expect(screen.getByText('复核的是这一轮完整的支持集合；只追加审计事件，不会改变回答或记忆。')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox',{name:/#1 猫咪/}));
    fireEvent.click(screen.getByRole('button',{name:'保存人工复核'}));
    await waitFor(()=>expect(ChatApi.prototype.request).toHaveBeenCalledWith(
      '/api/l2-sufficiency-shadow/turn-shadow/reviews','POST',{
        verdict:'incorrect',reason_code:'missed_support',expected_review_revision:0,
        expected_supported_scenario_ids:['scene-cat'],
      },
    ));
  });

  test('L1影子记录展示召回分数并只追加人工复核',async()=>{
    const feedback:MemoryFeedbackIndex={kind:'issues',offset:0,limit:25,total:0,counts:{memory_ok:0,recall_miss:0,wrong_memory:0,memory_irrelevant:0},review_counts:{open:0,resolved:0,dismissed:0},items:[]};
    const shadow:L1SufficiencyShadowPage={limit:20,runtime:{enabled:true,state:'completed'},review_counts:{completed:1,unreviewed:1,correct:0,incorrect:0,uncertain:0},policy_metrics:{reviewed_cases:0,labeled_cases:0,answerable_labeled_cases:0,unsupported_labeled_cases:0,excluded_latest_reviews:0,false_block_cases:0,unsupported_pass_cases:0,incomplete_allow_cases:0,overinclusive_allow_cases:0,original_candidate_count:0,kept_candidate_count:0,removed_candidate_count:0,candidate_reduction_rate:null,context_measured_cases:0,original_context_characters:0,kept_context_characters:0,context_character_reduction_rate:null,candidate_precision:null,candidate_recall:null,readiness:{policy_id:'l1-sufficiency-controlled-trial-readiness-v1',status:'not_ready',automatic_activation:false,minimum_cases_per_stratum:60,confidence_level:0.95,answerable_zero_error_upper_bound:null,unsupported_zero_error_upper_bound:null,conditions:[{code:'answerable_sample_floor',passed:false,actual:0,required:60}],limitations:[]}},items:[{
      user_message_id:'turn-l1-shadow',query:'豆包是什么颜色',retrieval_strategy:'keyword_dense_rrf_v1',reviewer_version:'gate-v2',provider:'openai_compatible',model:'deepseek-v4-flash',status:'completed',requested_at:'2026-09-13T02:00:00Z',completed_at:'2026-09-13T02:00:01Z',error_code:null,candidate_count:1,supported_count:0,review_verdict:null,review_revision:null,
    }]};
    const detail:L1SufficiencyShadowDetail={...shadow.items[0],prompt_sha256:'a'.repeat(64),candidates:[{
      memory_id:'memory-cat',rank:1,content_sha256:'b'.repeat(64),content_characters:13,keyword_score:1,dense_score:0.81,fused_score:0.03,supports_answer:0,reason_code:'missing_attribute',current_content:'用户养了一只叫豆包的猫。',current_status:'current',content_matches_snapshot:true,
    }],review:{verdict:null,reason_code:null,review_revision:0,occurred_at:null,expected_supported_memory_ids:null}};
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async path=>{
      if(path==='/api/l1-sufficiency-shadow?limit=20')return shadow as never;
      if(path==='/api/l1-sufficiency-shadow/turn-l1-shadow')return detail as never;
      return feedback as never;
    });
    render(<MemoryRouter><MemoryQualityApp/></MemoryRouter>);
    expect(await screen.findByText('豆包是什么颜色')).toBeTruthy();
    expect(screen.getByText('语义相关不等于足以回答')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'查看 L1 候选判断'}));
    expect(await screen.findByText('用户养了一只叫豆包的猫。')).toBeTruthy();
    expect(screen.getByText(/关键词 1 · 余弦 0.810 · 融合 0.0300/)).toBeTruthy();
    expect(screen.getByRole('link',{name:'打开 L1'}).getAttribute('href')).toBe('/memories?memory_id=memory-cat');
    fireEvent.click(screen.getByRole('button',{name:'L1 判断错误'}));
    const save=screen.getByRole('button',{name:/保存 L1 复核/});
    expect(save.hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('checkbox',{name:/#1 用户养了一只叫豆包的猫/}));
    expect(save.hasAttribute('disabled')).toBe(false);
    fireEvent.click(save);
    await waitFor(()=>expect(request).toHaveBeenCalledWith(
      '/api/l1-sufficiency-shadow/turn-l1-shadow/reviews','POST',{
        verdict:'incorrect',reason_code:'missed_support',expected_review_revision:0,
        expected_supported_memory_ids:['memory-cat'],
      },
    ));
  });
});
