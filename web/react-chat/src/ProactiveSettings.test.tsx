import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from './api';
import {ProactiveSettings} from './ProactiveSettings';
import {createConsoleQueryClient} from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('主动交流设置', () => {
  const scheduleStatus = {
    action:'wait', reason:'before_schedule', local_date:'2026-09-07',
    scheduled_for:null, user_chatted_today:false,
    awaiting_user_response:false, already_evaluated_today:false,
    development_override:null,
    latest_development_override:null,
  };
  test('默认关闭并明确保存不等于后台投递', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      subject_id:'user:self', enabled:false, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:0, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
      topic_enabled:false,
    });
    const client = createConsoleQueryClient();
    const api = new ChatApi();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={api} ready={true}/></QueryClientProvider>);
    expect(await screen.findByRole('region', {name:'主动交流概览'})).toBeTruthy();
    expect(screen.getByText('常用设置')).toBeTruthy();
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
        topic_enabled:false,
      }),
    ));
    view.unmount(); client.clear();
  });

  test('允许把周期频率调到一分钟并同步安全上限', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:0, allowed_end_minute:1439,
      daily_limit:1, minimum_interval_seconds:86340, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v3', revision:3, updated_at:null,
      automatic_enabled:true, automatic_interval_seconds:86400,
      scheduled_minute:780, greeting_text:'下午好。', topic_enabled:false,
    };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method, body) => {
      if (path === '/api/proactive-policy' && method === 'PUT') {
        return {...policy, ...(body as object), revision:4};
      }
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
      if (path.startsWith('/api/proactive-outreach?') || path.startsWith('/api/scenarios?')
          || path === '/api/proactive-topic-seeds' || path === '/api/companion-follow-ups'
          || path.startsWith('/api/memories?') || path === '/api/companion-strategy-candidates'
          || path.startsWith('/api/companion-user-initiated-interactions')
          || path === '/api/companion-routine-candidates'
          || path === '/api/companion-absence-strategy-versions') return {items:[],events:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);

    fireEvent.change(await screen.findByRole('spinbutton', {name:'主动交流频率（分钟）'}), {target:{value:'1'}});
    expect(await screen.findByText('当前是高频主动交流')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name:'保存主动交流设置'}));

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/api/proactive-policy', 'PUT', expect.objectContaining({
        automatic_interval_seconds:60,
        minimum_interval_seconds:0,
        daily_limit:1440,
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
        topic_enabled:false,
      };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
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
    fireEvent.click(await screen.findByText('测试与诊断'));
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
      topic_enabled:false,
    };
    const queued = {
      outreach_id:'a'.repeat(32), trigger:'manual_test', content:'合成问候',
      created_at:'2026-09-07T04:00:00+00:00', expires_at:'2026-09-07T04:05:00+00:00',
      state:'queued', revision:2, reason:'ready', event_count:2, failure_reason:null,
      topic_seed_id:null, topic_seed_revision:null, strategy_source:null,
    };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[queued]};
      if (path.endsWith('/confirm-played')) return {
        outreach_id:queued.outreach_id, state:'played', revision:3, replayed:false,
        policy_action:null, policy_reason:null, delivery_reason:null, device:null,
      };
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    fireEvent.click((await screen.findAllByText('最近运行记录'))[0]);
    fireEvent.click(await screen.findByRole('button', {name:'确认已听到'}));
    expect(await screen.findByText(/亲耳观察记录为 played/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith(
      `/api/proactive-outreach/${queued.outreach_id}/confirm-played`,
      'POST', {expected_revision:2},
    );
    expect(request.mock.calls.filter(([path]) => String(path).endsWith('/confirm-played'))).toHaveLength(1);
    view.unmount(); client.clear();
  });

  test('正式问候只把后续消息展示为时间证据', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:3, updated_at:null,
      automatic_enabled:true, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
      topic_enabled:false,
    };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[{
        outreach_id:'formal-1', trigger:'habit_candidate', content:'下午好',
        created_at:'2026-09-07T04:00:00+00:00', expires_at:'2026-09-07T04:05:00+00:00',
        state:'played', revision:3, reason:'user_confirmed_playback', event_count:3,
        failure_reason:null, topic_seed_id:null, topic_seed_revision:null,
        strategy_source:{
          version_id:'absence-version', selection_revision:2,
          evaluated_local_date:'2026-09-07', source_candidate_id:'routine-candidate',
          source_candidate_revision:1, expected_minute:720, grace_minutes:60,
          utc_offset_minutes:480, trigger_policy_version:'routine-absence-trigger-v1',
        },
        outcome_observation_state:'subsequent_user_message_observed',
        delivery_evidence_level:'played',
        subsequent_user_message:{
          occurred_at:'2026-09-07T04:03:00+00:00', latency_seconds:180,
          evidence:'temporal_order',
        },
        explicit_feedback:{
          topic_seed_id:'topic-1', occurred_at:'2026-09-07T04:03:00+00:00',
          feedback_kind:'reject_topic', action_kind:'topic_seed_disabled',
          evidence_kind:'user_explicit', interpreter_version:'explicit-topic-rejection-v1',
        },
      }]};
      if (path.startsWith('/api/scenarios?')) return {items:[]};
      if (path === '/api/proactive-topic-seeds') return {items:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);

    expect(await screen.findByText(/已观察（3 分钟后；仅表示时间先后）/)).toBeTruthy();
    expect(screen.getByText(/用户拒绝继续使用该话题/)).toBeTruthy();
    expect(screen.getByText(/习惯策略来源：版本 absence-version/)).toBeTruthy();
    expect(screen.getByText(/2026-09-07 在 13:00 检查/)).toBeTruthy();

    view.unmount(); client.clear();
  });

  test('话题素材必须由用户写明可播短句且保存本身不会投递', async () => {
    const policy = {
      subject_id:'user:self', enabled:false, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v2', revision:0, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好，今天过得怎么样？',
      topic_enabled:false,
    };
    const scenario = {id:'scenario-1',title:'毕业设计',summary:'用户正在准备毕业设计汇报。',revision:2};
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method) => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
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
    expect(await screen.findByText(/只有打开并保存记忆话题开关/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith('/api/proactive-topic-seeds', 'POST', {
      scenario_id:'scenario-1', expected_scenario_revision:2,
      prompt_text:'毕业设计准备得怎么样了？',
      request_id:'6a4db801-6779-40fc-90b4-aab77f580c82',
    });
    expect(request.mock.calls.some(([path]) => path === '/api/proactive-outreach/test')).toBe(false);
    view.unmount(); client.clear();
  });

  test('直接解释今天聊过和上一条仍待回应的定时拦截条件', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:3, minimum_interval_seconds:0, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v2', revision:3, updated_at:null,
      automatic_enabled:true, scheduled_minute:782, greeting_text:'下午好。', topic_enabled:true,
    };
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return {
        ...scheduleStatus, action:'skip', reason:'user_already_chatted_today',
        user_chatted_today:true, awaiting_user_response:true,
      };
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path.startsWith('/api/scenarios?')) return {items:[]};
      if (path === '/api/proactive-topic-seeds') return {items:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    expect(await screen.findByText('今天已经聊过，今天的每日问候会跳过')).toBeTruthy();
    expect(screen.getByText(/改成短于 24 小时的间隔后/)).toBeTruthy();
    expect(screen.getByText('正在等待你回应上一条主动问候')).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('显式创建一次性定时授权并显示目标时间', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:3, minimum_interval_seconds:0, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v2', revision:4, updated_at:null,
      automatic_enabled:true, scheduled_minute:790, greeting_text:'下午好。', topic_enabled:true,
    };
    let armed = false;
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method) => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return {
        ...scheduleStatus,
        development_override:armed ? {
          id:'a'.repeat(32), subject_id:'user:self', local_date:'2026-09-07',
          scheduled_minute:790, policy_revision:4, status:'armed', created_at:'2026-09-07T05:00:00Z',
          updated_at:'2026-09-07T05:00:00Z', consumption_reason:null, revision:1,
        } : null,
        latest_development_override:armed ? {
          id:'a'.repeat(32), subject_id:'user:self', local_date:'2026-09-07',
          scheduled_minute:790, policy_revision:4, status:'armed',
          created_at:'2026-09-07T05:00:00Z', updated_at:'2026-09-07T05:00:00Z',
          consumption_reason:null, revision:1,
        } : null,
      };
      if (path === '/api/proactive-schedule-override/arm' && method === 'POST') {
        armed = true; return {status:'armed'};
      }
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path.startsWith('/api/scenarios?')) return {items:[]};
      if (path === '/api/proactive-topic-seeds') return {items:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    fireEvent.click(await screen.findByText('测试与诊断'));
    fireEvent.click(await screen.findByRole('button', {name:'允许下一次定时验证'}));
    expect(await screen.findByText(/已授权下一次开发定时验证/)).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/已授权 2026-09-07 13:10/)).toBeTruthy());
    expect(request).toHaveBeenCalledWith('/api/proactive-schedule-override/arm', 'POST', {
      expected_policy_revision:4, confirm_action:true,
    });
    view.unmount(); client.clear();
  });

  test('策略分析只创建未生效候选并展示逐条时间来源', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v2', revision:3, updated_at:null,
      automatic_enabled:true, scheduled_minute:780, greeting_text:'下午好。', topic_enabled:false,
    };
    const candidate = {
      id:'a'.repeat(32), subject_id:'user:self', status:'candidate' as const,
      suggested_minute:782, utc_offset_minutes:480, evidence_count:3,
      distinct_local_dates:3,
      rationale_code:'repeated_temporal_followup_near_contact_time' as const,
      generator_version:'contact-time-candidate-v1',
      created_at:'2026-09-07T05:00:00Z', updated_at:'2026-09-07T05:00:00Z',
      revision:1, active:false as const,
      sources:[0,1,2].map(day => ({
        interaction_event_id:`event-${day}`, outreach_id:`outreach-${day}`,
        queued_at:`2026-09-0${day + 1}T05:02:00Z`,
        observed_at:`2026-09-0${day + 1}T05:04:00Z`, latency_seconds:120,
        local_date:`2026-09-0${day + 1}`, local_minute:782,
        delivery_evidence_level:'server_queued' as const,
      })),
    };
    let created = false;
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method) => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path.startsWith('/api/scenarios?')) return {items:[]};
      if (path === '/api/proactive-topic-seeds') return {items:[]};
      if (path === '/api/companion-strategy-candidates') return {items:created ? [candidate] : []};
      if (path.startsWith('/api/companion-user-initiated-interactions')) return {items:[{
        id:'event-first', subject_id:'user:self', source_message_id:'message-first',
        occurred_at:'2026-09-01T05:00:00Z', previous_user_message_at:null,
        silence_gap_seconds:null,
        evidence_kind:'silence_gap_without_recent_outreach',
        detector_version:'user-initiated-interaction-v1',
        local_date:'2026-09-01', local_minute:780, utc_offset_minutes:480,
      }]};
      if (path === '/api/companion-routine-candidates') return {items:[{
        id:'b'.repeat(32), subject_id:'user:self', status:'candidate',
        expected_minute:780, utc_offset_minutes:480,
        observation_window_minutes:30, evidence_count:3,
        distinct_local_dates:3,
        rationale_code:'repeated_user_initiated_activity_near_time',
        generator_version:'user-initiated-routine-candidate-v1',
        created_at:'2026-09-07T05:00:00Z', updated_at:'2026-09-07T05:00:00Z',
        revision:1, active:false,
        sources:[{user_initiated_event_id:'event-first',
          occurred_at:'2026-09-01T05:00:00Z', silence_gap_seconds:null,
          evidence_kind:'silence_gap_without_recent_outreach',
          local_date:'2026-09-01', local_minute:780}],
      }]};
      if (path === '/api/companion-strategy-candidates/analyze' && method === 'POST') {
        created = true;
        return {outcome:'candidate_created', eligible_observation_count:3,
          distinct_local_dates:3, candidate};
      }
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);

    fireEvent.click(await screen.findByRole('button', {name:'分析现有互动记录'}));

    expect(await screen.findByText(/已形成一条待观察候选/)).toBeTruthy();
    expect(await screen.findByText('建议试验 13:02')).toBeTruthy();
    expect(screen.getByText(/不能证明你喜欢该时段/)).toBeTruthy();
    expect(screen.getAllByText(/2 分钟后出现用户消息/)).toHaveLength(3);
    expect(screen.getByText('用户主动出现时间观察')).toBeTruthy();
    expect(await screen.findByText(/第一条可观察用户消息/)).toBeTruthy();
    expect(await screen.findByText('常在 13:00 左右主动出现')).toBeTruthy();
    expect(screen.getByText(/不是主动联系规则/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith(
      '/api/companion-strategy-candidates/analyze', 'POST', {},
    );
    expect(request.mock.calls.some(([path]) => path === '/api/proactive-policy' && request.mock.calls.some(call => call[1] === 'PUT'))).toBe(false);
    view.unmount(); client.clear();
  });

  test('从当前 L1 建立跟进候选但不创建主动消息', async () => {
    const policy = {
      subject_id:'user:self', enabled:false, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:540, allowed_end_minute:1260,
      daily_limit:1, minimum_interval_seconds:21600, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:0, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好。', topic_enabled:false,
    };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method, body) => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path === '/api/memories?state=active&offset=0&limit=100&q=') return {items:[{id:'memory-1',content:'用户计划周五完善毕业设计汇报。',state:'active'}]};
      if (path === '/api/memories/memory-1') return {revision:'a'.repeat(64)};
      if (path === '/api/companion-follow-ups' && method === 'POST') return {
        id:'b'.repeat(32), subject_id:'user:self', source_memory_id:'memory-1',
        prompt_text:(body as {prompt_text:string}).prompt_text,
        follow_up_at:(body as {follow_up_at:string}).follow_up_at,
        status:'candidate', created_at:'2026-09-10T01:00:00Z', updated_at:'2026-09-10T01:00:00Z',
        revision:1, due:false, ready_for_activation:true, blocked_reason:null,
        source:{layer:'l1',content:'用户计划周五完善毕业设计汇报。',state:'active',superseded_by_id:null},
      };
      if (path === '/api/companion-follow-ups') return {items:[]};
      if (path.startsWith('/api/scenarios?') || path === '/api/proactive-topic-seeds'
          || path === '/api/companion-strategy-candidates'
          || path.startsWith('/api/companion-user-initiated-interactions')
          || path === '/api/companion-routine-candidates'
          || path === '/api/companion-absence-strategy-versions') return {items:[],events:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    fireEvent.mouseDown(await screen.findByLabelText('跟进来源 L1'));
    fireEvent.click(await screen.findByText('用户计划周五完善毕业设计汇报。'));
    fireEvent.change(screen.getByLabelText('以后适合问的一句话'), {target:{value:'毕业设计汇报准备得怎么样了？'}});
    fireEvent.change(screen.getByLabelText('计划跟进时间'), {target:{value:'2030-01-01T12:00'}});
    fireEvent.click(screen.getByRole('button', {name:'建立跟进候选'}));
    expect(await screen.findByText(/跟进候选已保存并绑定 L1 来源/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith('/api/companion-follow-ups', 'POST', expect.objectContaining({
      source_memory_id:'memory-1', expected_memory_revision:'a'.repeat(64),
      prompt_text:'毕业设计汇报准备得怎么样了？',
    }));
    expect(request.mock.calls.some(([path]) => path === '/api/proactive-outreach/test')).toBe(false);
    view.unmount(); client.clear();
  });

  test('显式启用才为跟进建立一次性账本', async () => {
    const policy = {
      subject_id:'user:self', enabled:true, utc_offset_minutes:480,
      allowed_weekdays:[0,1,2,3,4,5,6], allowed_start_minute:0, allowed_end_minute:1439,
      daily_limit:2, minimum_interval_seconds:0, maximum_lifetime_seconds:300,
      quiet_until:null, policy_version:'proactive-contact-policy-v1', revision:3, updated_at:null,
      automatic_enabled:false, scheduled_minute:780, greeting_text:'下午好。', topic_enabled:false,
    };
    const candidate = {
      id:'c'.repeat(32), subject_id:'user:self', source_memory_id:'memory-1',
      prompt_text:'毕业设计汇报准备得怎么样了？', follow_up_at:'2030-01-01T04:00:00Z',
      status:'candidate', created_at:'2026-09-10T01:00:00Z', updated_at:'2026-09-10T01:00:00Z',
      revision:1, due:false, ready_for_activation:true, blocked_reason:null, activation:null,
      source:{layer:'l1',content:'用户计划完善毕业设计汇报。',state:'active',superseded_by_id:null},
    };
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method) => {
      if (path === '/api/proactive-policy') return policy;
      if (path === '/api/proactive-schedule-status') return scheduleStatus;
      if (path.startsWith('/api/proactive-outreach?')) return {items:[]};
      if (path === '/api/companion-follow-ups' && method !== 'POST') return {items:[candidate]};
      if (path.endsWith('/arm')) return {...candidate,ready_for_activation:false,
        blocked_reason:'already_activated',activation:{outreach_id:'d'.repeat(32),state:'candidate',revision:1,expires_at:'2030-01-01T04:05:00Z'}};
      if (path.startsWith('/api/scenarios?') || path === '/api/proactive-topic-seeds'
          || path.startsWith('/api/memories?') || path === '/api/companion-strategy-candidates'
          || path.startsWith('/api/companion-user-initiated-interactions')
          || path === '/api/companion-routine-candidates'
          || path === '/api/companion-absence-strategy-versions') return {items:[],events:[]};
      throw new Error(`unexpected path: ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><ProactiveSettings api={new ChatApi()} ready={true}/></QueryClientProvider>);
    fireEvent.click(await screen.findByText('一次性事项跟进'));
    fireEvent.click(await screen.findByRole('button', {name:'启用一次跟进'}));
    expect(await screen.findByText(/跟进已启用为一次性未来任务/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith(
      `/api/companion-follow-ups/${candidate.id}/arm`, 'POST',
      {expected_revision:1,expected_policy_revision:3},
    );
    expect(request.mock.calls.some(([path]) => path === '/api/proactive-outreach/test')).toBe(false);
    view.unmount(); client.clear();
  });
});
