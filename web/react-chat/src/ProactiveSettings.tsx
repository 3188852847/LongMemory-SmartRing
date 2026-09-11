import {useEffect, useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Checkbox, Input, InputNumber, Space, Switch} from 'antd';
import {ApiError, ChatApi, type CompanionAbsenceStrategyVersion, type CompanionAbsenceStrategyVersionList, type CompanionRoutineCandidate, type CompanionStrategyCandidate, type FollowUpCandidate, type ProactiveOutreachSummary, type ProactivePolicy, type ProactiveScheduleStatus, type ProactiveTestResult, type ProactiveTopicSeed, type UserInitiatedInteraction} from './api';
import {ProactiveHistorySection} from './ProactiveHistorySection';
import {ProactiveTopicSection} from './ProactiveTopicSection';
import {ProactiveFollowUpSection} from './ProactiveFollowUpSection';
import {CompanionLearningSection} from './CompanionLearningSection';
import {minuteText, parseMinute} from './proactiveTime';

const DAYS = ['周一','周二','周三','周四','周五','周六','周日'].map((label, value) => ({label, value}));
const overrideResultText = (reason:string | null) => ({
  scheduled_attempt_started:'已到点并开始尝试',
  scheduled_minute_missed:'已错过设定时刻',
  configuration_changed_or_date_expired:'日期或设置已经变化',
  automatic_setting_disabled:'后台定时已经关闭',
  weekday_no_longer_allowed:'当天星期已不再允许',
  owner_cancelled:'由你主动撤销',
}[reason ?? ''] ?? reason ?? '未记录原因');

/** 编辑明确许可边界；保存设置不会调用模型、创建候选或向设备投递。 */
export function ProactiveSettings({api, ready}:{api:ChatApi; ready:boolean}) {
  const client = useQueryClient();
  const query = useQuery({queryKey:['proactive-policy'], queryFn:() => api.request<ProactivePolicy>('/api/proactive-policy'), enabled:ready});
  const scheduleStatus = useQuery({
    queryKey:['proactive-schedule-status'],
    queryFn:() => api.request<ProactiveScheduleStatus>('/api/proactive-schedule-status'),
    enabled:ready, refetchInterval:30000,
  });
  const history = useQuery({queryKey:['proactive-outreach'], queryFn:() => api.request<{items:ProactiveOutreachSummary[]}>('/api/proactive-outreach?limit=10'), enabled:ready});
  const scenarios = useQuery({queryKey:['proactive-topic-scenarios'], queryFn:() => api.request<{items:Array<{id:string;title:string;summary:string;revision:number}>}>('/api/scenarios?state=active&offset=0&limit=100'), enabled:ready});
  const topicSeeds = useQuery({queryKey:['proactive-topic-seeds'], queryFn:() => api.request<{items:ProactiveTopicSeed[]}>('/api/proactive-topic-seeds'), enabled:ready});
  const followUpSources = useQuery({queryKey:['follow-up-l1-sources'], queryFn:() => api.request<{items:Array<{id:string;content:string;state:string}>}>('/api/memories?state=active&offset=0&limit=100&q='), enabled:ready});
  const followUps = useQuery({queryKey:['companion-follow-ups'], queryFn:() => api.request<{items:FollowUpCandidate[]}>('/api/companion-follow-ups'), enabled:ready});
  const strategyCandidates = useQuery({queryKey:['companion-strategy-candidates'], queryFn:() => api.request<{items:CompanionStrategyCandidate[]}>('/api/companion-strategy-candidates'), enabled:ready});
  const userInitiated = useQuery({queryKey:['companion-user-initiated-interactions'], queryFn:() => api.request<{items:UserInitiatedInteraction[]}>('/api/companion-user-initiated-interactions?limit=10'), enabled:ready});
  const routineCandidates = useQuery({queryKey:['companion-routine-candidates'], queryFn:() => api.request<{items:CompanionRoutineCandidate[]}>('/api/companion-routine-candidates'), enabled:ready});
  const absenceVersions = useQuery({queryKey:['companion-absence-strategy-versions'], queryFn:() => api.request<CompanionAbsenceStrategyVersionList>('/api/companion-absence-strategy-versions'), enabled:ready});
  const [draft, setDraft] = useState<ProactivePolicy>();
  const [notice, setNotice] = useState('');
  const [testText, setTestText] = useState('今天也要照顾好自己呀。');
  const [testNotice, setTestNotice] = useState('');
  const [topicScenarioId, setTopicScenarioId] = useState<string>();
  const [topicText, setTopicText] = useState('');
  const [topicNotice, setTopicNotice] = useState('');
  const [followUpSourceId, setFollowUpSourceId] = useState<string>();
  const [followUpText, setFollowUpText] = useState('');
  const [followUpLocal, setFollowUpLocal] = useState('');
  const [followUpNotice, setFollowUpNotice] = useState('');
  const [strategyNotice, setStrategyNotice] = useState('');
  const [routineNotice, setRoutineNotice] = useState('');
  const [absenceVersionNotice, setAbsenceVersionNotice] = useState('');
  useEffect(() => {if (query.data) setDraft({...query.data, allowed_weekdays:[...query.data.allowed_weekdays]});}, [query.data]);
  const dirty = useMemo(() => Boolean(draft && query.data && JSON.stringify(draft) !== JSON.stringify(query.data)), [draft, query.data]);
  const mutation = useMutation({
    mutationFn:(value:ProactivePolicy) => api.request<ProactivePolicy>('/api/proactive-policy', 'PUT', {
      expected_revision:value.revision, enabled:value.enabled, utc_offset_minutes:value.utc_offset_minutes,
      allowed_weekdays:value.allowed_weekdays, allowed_start_minute:value.allowed_start_minute,
      allowed_end_minute:value.allowed_end_minute, daily_limit:value.daily_limit,
      minimum_interval_seconds:value.minimum_interval_seconds,
      maximum_lifetime_seconds:value.maximum_lifetime_seconds, quiet_until:value.quiet_until,
      automatic_enabled:value.automatic_enabled, scheduled_minute:value.scheduled_minute,
      greeting_text:value.greeting_text, topic_enabled:value.topic_enabled,
    }),
    onSuccess:value => {client.setQueryData(['proactive-policy'], value); setDraft({...value, allowed_weekdays:[...value.allowed_weekdays]}); setNotice(value.automatic_enabled ? '设置已保存；后台只会在指定分钟检查一次。' : '设置已保存；后台定时问候保持关闭。'); void client.invalidateQueries({queryKey:['proactive-schedule-status']});},
    onError:error => {setNotice(error instanceof ApiError && error.code === 'proactive_settings_conflict' ? '设置已被另一个页面修改，请重新读取后再保存。' : '保存失败，未自动重试。'); void client.invalidateQueries({queryKey:['proactive-policy']});},
  });
  const testMutation = useMutation({
    mutationFn:() => api.request<ProactiveTestResult>('/api/proactive-outreach/test', 'POST', {
      text:testText, request_id:crypto.randomUUID(), expected_policy_revision:draft!.revision,
    }),
    onSuccess:value => {
      void client.invalidateQueries({queryKey:['proactive-outreach']});
      if (value.state === 'queued') {
        setTestNotice('小智服务已接收并排队；当前协议不能确认圆屏已经播放，请以实机声音为准。');
      } else if (value.state === 'blocked') {
        setTestNotice(`策略已拦截，本次没有发送（原因：${value.policy_reason ?? '未知'}）。`);
      } else {
        setTestNotice(`本次未排队（状态：${value.state}；原因：${value.delivery_reason ?? value.policy_reason ?? '未知'}）。`);
      }
    },
    onError:error => setTestNotice(
      error instanceof ApiError && error.code === 'proactive_settings_conflict'
        ? '设置已在别处变化，请刷新设置后再测试。'
        : '测试请求失败且没有自动重试；请检查小智服务和圆屏连接。'
    ),
  });
  const armScheduleTest = useMutation({
    mutationFn:() => api.request('/api/proactive-schedule-override/arm', 'POST', {
      expected_policy_revision:draft!.revision, confirm_action:true,
    }),
    onSuccess:() => {
      setNotice('已授权下一次开发定时验证；到点后无论成功、拦截或错过都会自动失效。');
      void client.invalidateQueries({queryKey:['proactive-schedule-status']});
    },
    onError:error => setNotice(
      error instanceof ApiError && error.code === 'proactive_schedule_override_time_not_future'
        ? '授权失败：请先把定时问候设置为今天稍后的时间并保存。'
        : error instanceof ApiError && error.code === 'proactive_schedule_override_already_armed'
        ? '已经存在一次待执行授权；请先撤销或等待它被消费。'
        : '一次性定时授权没有创建，请核对总开关、后台定时、星期和未保存设置。'
    ),
  });
  const cancelScheduleTest = useMutation({
    mutationFn:() => api.request(
      `/api/proactive-schedule-override/${scheduleStatus.data!.development_override!.id}/cancel`,
      'POST', {expected_revision:scheduleStatus.data!.development_override!.revision},
    ),
    onSuccess:() => {
      setNotice('已撤销一次性开发定时授权。');
      void client.invalidateQueries({queryKey:['proactive-schedule-status']});
    },
    onError:() => {
      setNotice('撤销失败，授权可能已经被后台消费；正在重新读取状态。');
      void client.invalidateQueries({queryKey:['proactive-schedule-status']});
    },
  });
  const confirmMutation = useMutation({
    mutationFn:(item:ProactiveOutreachSummary) => api.request<ProactiveTestResult>(
      `/api/proactive-outreach/${item.outreach_id}/confirm-played`, 'POST',
      {expected_revision:item.revision},
    ),
    onSuccess:() => {
      setTestNotice('已按你的亲耳观察记录为 played；这不是设备自动回执。');
      void client.invalidateQueries({queryKey:['proactive-outreach']});
    },
    onError:error => {
      setTestNotice(error instanceof ApiError && error.code === 'proactive_outreach_conflict'
        ? '记录已发生变化，请刷新后再确认。'
        : '没有写入“已播放”；请刷新记录并核对当前状态。');
      void client.invalidateQueries({queryKey:['proactive-outreach']});
    },
  });
  const createTopic = useMutation({
    mutationFn:() => {
      const scenario = scenarios.data!.items.find(item => item.id === topicScenarioId)!;
      return api.request<ProactiveTopicSeed>('/api/proactive-topic-seeds', 'POST', {
        scenario_id:scenario.id, expected_scenario_revision:scenario.revision,
        prompt_text:topicText, request_id:crypto.randomUUID(),
      });
    },
    onSuccess:() => {
      setTopicScenarioId(undefined); setTopicText('');
      setTopicNotice('安全话题素材已保存；只有打开并保存记忆话题开关后，定时任务才可能使用它。');
      void client.invalidateQueries({queryKey:['proactive-topic-seeds']});
    },
    onError:error => {
      setTopicNotice(error instanceof ApiError && error.code === 'topic_seed_scenario_conflict'
        ? '来源场景已经变化，请刷新后重新核对。'
        : '话题素材没有保存，请核对来源场景和短句。');
      void client.invalidateQueries({queryKey:['proactive-topic-scenarios']});
    },
  });
  const disableTopic = useMutation({
    mutationFn:(seed:ProactiveTopicSeed) => api.request(
      `/api/proactive-topic-seeds/${seed.id}/disable`, 'POST',
      {expected_revision:seed.revision},
    ),
    onSuccess:() => {
      setTopicNotice('话题素材已停用并保留审计记录。');
      void client.invalidateQueries({queryKey:['proactive-topic-seeds']});
    },
    onError:() => {
      setTopicNotice('停用失败，页面将重新读取最新状态。');
      void client.invalidateQueries({queryKey:['proactive-topic-seeds']});
    },
  });
  const createFollowUp = useMutation({
    mutationFn:async() => {
      const detail = await api.request<{revision:string}>(
        `/api/memories/${encodeURIComponent(followUpSourceId!)}`,
      );
      return api.request<FollowUpCandidate>('/api/companion-follow-ups', 'POST', {
        source_memory_id:followUpSourceId,
        expected_memory_revision:detail.revision,
        prompt_text:followUpText,
        follow_up_at:new Date(followUpLocal).toISOString(),
        request_id:crypto.randomUUID(),
      });
    },
    onSuccess:() => {
      setFollowUpSourceId(undefined); setFollowUpText(''); setFollowUpLocal('');
      setFollowUpNotice('跟进候选已保存并绑定 L1 来源；当前版本不会自动发送。');
      void client.invalidateQueries({queryKey:['companion-follow-ups']});
    },
    onError:error => {
      setFollowUpNotice(error instanceof ApiError && error.code === 'follow_up_source_conflict'
        ? '来源 L1 已变化，请重新选择并核对。'
        : error instanceof ApiError && error.code === 'follow_up_time_not_future'
        ? '跟进时间必须晚于现在。'
        : '跟进候选没有保存，请核对来源、短句和时间。');
      void client.invalidateQueries({queryKey:['follow-up-l1-sources']});
      void client.invalidateQueries({queryKey:['companion-follow-ups']});
    },
  });
  const cancelFollowUp = useMutation({
    mutationFn:(item:FollowUpCandidate) => api.request(
      `/api/companion-follow-ups/${item.id}/cancel`, 'POST',
      {expected_revision:item.revision},
    ),
    onSuccess:() => {
      setFollowUpNotice('跟进候选已取消；没有创建或投递主动消息。');
      void client.invalidateQueries({queryKey:['companion-follow-ups']});
    },
    onError:() => {
      setFollowUpNotice('候选状态已经变化或取消失败；正在重新读取。');
      void client.invalidateQueries({queryKey:['companion-follow-ups']});
    },
  });
  const armFollowUp = useMutation({
    mutationFn:(item:FollowUpCandidate) => api.request<FollowUpCandidate>(
      `/api/companion-follow-ups/${item.id}/arm`, 'POST', {
        expected_revision:item.revision,
        expected_policy_revision:draft!.revision,
      },
    ),
    onSuccess:() => {
      setFollowUpNotice('跟进已启用为一次性未来任务；到点仍会经过全部主动交流护栏。');
      void client.invalidateQueries({queryKey:['companion-follow-ups']});
      void client.invalidateQueries({queryKey:['proactive-outreach']});
    },
    onError:error => {
      setFollowUpNotice(error instanceof ApiError && error.code === 'follow_up_requires_proactive_enabled'
        ? '请先打开并保存主动交流总许可，再启用跟进。'
        : error instanceof ApiError && error.code === 'proactive_settings_conflict'
        ? '主动交流设置已经变化，请刷新后再启用。'
        : '跟进未启用；来源、时间或候选状态可能已经变化。');
      void client.invalidateQueries({queryKey:['companion-follow-ups']});
      void client.invalidateQueries({queryKey:['proactive-policy']});
    },
  });
  const analyzeStrategy = useMutation({
    mutationFn:() => api.request<{
      outcome:string; eligible_observation_count:number; distinct_local_dates:number;
      candidate:CompanionStrategyCandidate | null;
    }>('/api/companion-strategy-candidates/analyze', 'POST', {}),
    onSuccess:value => {
      if (value.outcome === 'candidate_created') {
        setStrategyNotice('已形成一条待观察候选；它尚未修改定时问候，也不是用户画像。');
      } else if (value.outcome === 'current_candidate_exists') {
        setStrategyNotice('已有一条待观察候选，本次没有重复创建。');
      } else if (value.outcome === 'evidence_already_analyzed') {
        setStrategyNotice('这些来源已经分析过，本次没有重新创建。');
      } else {
        setStrategyNotice(`跨日证据不足：当前有 ${value.eligible_observation_count} 条合格观察，最佳时段覆盖 ${value.distinct_local_dates}/3 个不同日期。`);
      }
      void client.invalidateQueries({queryKey:['companion-strategy-candidates']});
    },
    onError:() => setStrategyNotice('分析没有完成；不会自动重试，也没有修改主动联系设置。'),
  });
  const dismissStrategy = useMutation({
    mutationFn:(candidate:CompanionStrategyCandidate) => api.request<CompanionStrategyCandidate>(
      `/api/companion-strategy-candidates/${candidate.id}/dismiss`, 'POST',
      {expected_revision:candidate.revision},
    ),
    onSuccess:() => {
      setStrategyNotice('候选已忽略并保留来源记录；主动联系设置没有变化。');
      void client.invalidateQueries({queryKey:['companion-strategy-candidates']});
    },
    onError:() => {
      setStrategyNotice('候选状态已经变化或操作失败；正在重新读取。');
      void client.invalidateQueries({queryKey:['companion-strategy-candidates']});
    },
  });
  const analyzeRoutine = useMutation({
    mutationFn:() => api.request<{
      outcome:string; eligible_observation_count:number; distinct_local_dates:number;
      candidate:CompanionRoutineCandidate | null;
    }>('/api/companion-routine-candidates/analyze', 'POST', {}),
    onSuccess:value => {
      if (value.outcome === 'candidate_created') {
        setRoutineNotice('已形成一条用户主动出现时段候选；它不会自动联系或修改定时设置。');
      } else if (value.outcome === 'current_candidate_exists') {
        setRoutineNotice('已有一条待观察的主动出现时段候选，本次没有重复创建。');
      } else if (value.outcome === 'evidence_already_analyzed') {
        setRoutineNotice('这些时间来源已经分析过，本次没有重新创建。');
      } else {
        setRoutineNotice(`跨日证据不足：当前有 ${value.eligible_observation_count} 条主动出现观察，最佳时段覆盖 ${value.distinct_local_dates}/3 个不同日期。`);
      }
      void client.invalidateQueries({queryKey:['companion-routine-candidates']});
    },
    onError:() => setRoutineNotice('分析没有完成；没有创建候选，也没有修改主动联系设置。'),
  });
  const dismissRoutine = useMutation({
    mutationFn:(candidate:CompanionRoutineCandidate) => api.request<CompanionRoutineCandidate>(
      `/api/companion-routine-candidates/${candidate.id}/dismiss`, 'POST',
      {expected_revision:candidate.revision},
    ),
    onSuccess:() => {
      setRoutineNotice('主动出现时段候选已忽略，来源记录继续保留。');
      void client.invalidateQueries({queryKey:['companion-routine-candidates']});
    },
    onError:() => {
      setRoutineNotice('候选状态已经变化或操作失败；正在重新读取。');
      void client.invalidateQueries({queryKey:['companion-routine-candidates']});
    },
  });
  const createAbsenceVersion = useMutation({
    mutationFn:(candidate:CompanionRoutineCandidate) => api.request<{
      outcome:'version_created'|'version_exists'; version:CompanionAbsenceStrategyVersion;
    }>('/api/companion-absence-strategy-versions/draft', 'POST', {
      candidate_id:candidate.id, expected_candidate_revision:candidate.revision,
    }),
    onSuccess:value => {
      setAbsenceVersionNotice(value.outcome === 'version_created'
        ? '离线验证草案已保存；它尚未激活，也不会参与后台问候。'
        : '同一候选和回放数据已经有版本，本次没有重复创建。');
      void client.invalidateQueries({queryKey:['companion-absence-strategy-versions']});
    },
    onError:error => {
      setAbsenceVersionNotice(error instanceof ApiError && error.code === 'companion_absence_strategy_unsupported'
        ? '该时段加上宽限会跨越午夜，第一版不会猜测应归属哪一天。'
        : '草案没有保存；候选可能已经被忽略或发生变化。');
      void client.invalidateQueries({queryKey:['companion-routine-candidates']});
    },
  });
  const switchAbsenceVersion = useMutation({
    mutationFn:({version, rollback}:{version:CompanionAbsenceStrategyVersion;rollback:boolean}) => api.request(
      `/api/companion-absence-strategy-versions/${rollback ? 'rollback' : 'activate'}`, 'POST',
      {version_id:version.id, expected_revision:absenceVersions.data!.selection.revision},
    ),
    onSuccess:() => {
      setAbsenceVersionNotice('当前策略已激活并写入审计事件；到达缺席检查分钟后仍会经过主动交流总开关和全部安全门控。');
      void client.invalidateQueries({queryKey:['companion-absence-strategy-versions']});
    },
    onError:() => {
      setAbsenceVersionNotice('版本未切换；可能是页面修订已过期或离线门控未通过。');
      void client.invalidateQueries({queryKey:['companion-absence-strategy-versions']});
    },
  });
  const deactivateAbsenceVersion = useMutation({
    mutationFn:() => api.request('/api/companion-absence-strategy-versions/deactivate', 'POST', {
      expected_revision:absenceVersions.data!.selection.revision,
    }),
    onSuccess:() => {
      setAbsenceVersionNotice('当前策略已停用，旧版本和切换审计仍完整保留。');
      void client.invalidateQueries({queryKey:['companion-absence-strategy-versions']});
    },
    onError:() => {
      setAbsenceVersionNotice('停用没有生效；页面将读取最新修订。');
      void client.invalidateQueries({queryKey:['companion-absence-strategy-versions']});
    },
  });
  const change = (patch:Partial<ProactivePolicy>) => draft && setDraft({...draft, ...patch});
  if (query.isError) return <Alert type="error" showIcon title="主动交流设置不可用" description="请确认已选择当前版本的个人数据库。"/>;
  if (query.isLoading || !draft) return <Alert type="info" showIcon title="正在读取主动交流设置…"/>;
  const quietActive = draft.quiet_until && new Date(draft.quiet_until).getTime() > Date.now();
  const scheduleInsideWindow = draft.allowed_start_minute < draft.allowed_end_minute
    ? draft.scheduled_minute >= draft.allowed_start_minute && draft.scheduled_minute < draft.allowed_end_minute
    : draft.scheduled_minute >= draft.allowed_start_minute || draft.scheduled_minute < draft.allowed_end_minute;
  return <Space className="proactive-settings" orientation="vertical" style={{width:'100%'}}>
    <section className="proactive-overview" aria-label="主动交流概览">
      <div><small>主动联系许可</small><strong className={draft.enabled ? 'is-positive' : ''}>{draft.enabled ? '已开启' : '已关闭'}</strong></div>
      <div><small>后台定时</small><strong>{draft.automatic_enabled ? minuteText(draft.scheduled_minute) : '已关闭'}</strong></div>
      <div><small>今日对话</small><strong>{scheduleStatus.data?.user_chatted_today ? '已聊过' : '未观察'}</strong></div>
      <div><small>上次问候</small><strong className={scheduleStatus.data?.awaiting_user_response ? 'is-warning' : ''}>{scheduleStatus.data?.awaiting_user_response ? '等待回应' : '无待回应'}</strong></div>
    </section>
    <Alert type={draft.automatic_enabled ? 'warning' : 'success'} showIcon
      title={draft.automatic_enabled ? '后台定时问候已开启' : (draft.enabled ? '主动联系许可已打开，定时问候仍关闭' : '主动交流当前关闭')}
      description="定时问候只在所选星期的指定分钟检查：当天已经聊过、设备离线或忙碌、处于勿扰或错过时刻都会跳过，之后不补发。"/>
    {scheduleStatus.data?.user_chatted_today && <Alert type="info" showIcon
      title="今天已经聊过，今天的定时问候会跳过"
      description="这是避免刚聊完又主动打扰的既定规则；修改定时时刻不会绕过它。手动验证仍可使用。"/>}
    {scheduleStatus.data?.awaiting_user_response && <Alert type="warning" showIcon
      title="上一条主动问候之后还没有收到新的用户消息"
      description="自动定时会继续停止追问；真正说出并保存一条新消息后会解除。所有者手动验证不受这一项限制。"/>}
    {scheduleStatus.isError && <Alert type="error" showIcon title="暂时无法读取今天的定时状态"/>}
    <section className="settings-section">
      <h3>开发阶段：一次性定时验证</h3>
      <p className="subtle">授权后，今天下一次设定时刻可临时绕过“今天聊过”和“上一条待回应”。它不会绕过总开关、星期/时段、勿扰、频率或设备忙碌，也不会自动延续到下一天。</p>
      {scheduleStatus.data?.development_override ? <Alert type="warning" showIcon
        title={`已授权 ${scheduleStatus.data.development_override.local_date} ${minuteText(scheduleStatus.data.development_override.scheduled_minute)}`}
        description="到点后无论发送、拦截还是错过都会消费本次授权。"/> : <p className="subtle">当前没有待执行的一次性授权。</p>}
      {!scheduleStatus.data?.development_override && scheduleStatus.data?.latest_development_override && <p className="subtle">
        最近一次授权：{scheduleStatus.data.latest_development_override.status === 'cancelled' ? '已撤销' : '已消费'} · {overrideResultText(scheduleStatus.data.latest_development_override.consumption_reason)}
      </p>}
      <Space>
        <Button type="primary" loading={armScheduleTest.isPending}
          disabled={dirty || !draft.enabled || !draft.automatic_enabled || Boolean(scheduleStatus.data?.development_override) || armScheduleTest.isPending}
          onClick={() => armScheduleTest.mutate()}>允许下一次定时验证</Button>
        <Button danger loading={cancelScheduleTest.isPending}
          disabled={!scheduleStatus.data?.development_override || cancelScheduleTest.isPending}
          onClick={() => cancelScheduleTest.mutate()}>撤销一次性授权</Button>
      </Space>
    </section>
    <section className="settings-section proactive-policy-section">
    <h3>联系许可与时间边界</h3>
    <p className="subtle">这些是所有自动问候都必须通过的总边界；修改后需要显式保存。</p>
    <div className="setting-line"><span>允许主动联系</span><Switch aria-label="允许主动联系" checked={draft.enabled} onChange={enabled => change({enabled, ...(!enabled ? {automatic_enabled:false, topic_enabled:false} : {})})}/></div>
    <div className="setting-line"><span>后台定时问候</span><Switch aria-label="后台定时问候" disabled={!draft.enabled} checked={draft.automatic_enabled} onChange={automatic_enabled => change({automatic_enabled, ...(!automatic_enabled ? {topic_enabled:false} : {})})}/></div>
    <label>允许星期</label>
    <Checkbox.Group aria-label="允许星期" options={DAYS} value={draft.allowed_weekdays} onChange={values => change({allowed_weekdays:values.map(Number).sort()})}/>
    <div className="proactive-fields">
      <div><label htmlFor="proactive-start">开始时间</label><Input id="proactive-start" type="time" value={minuteText(draft.allowed_start_minute)} onChange={event => change({allowed_start_minute:parseMinute(event.target.value)})}/></div>
      <div><label htmlFor="proactive-end">结束时间</label><Input id="proactive-end" type="time" value={minuteText(draft.allowed_end_minute)} onChange={event => change({allowed_end_minute:parseMinute(event.target.value)})}/></div>
      <div><label htmlFor="proactive-daily">每天最多次数</label><InputNumber id="proactive-daily" min={1} max={20} value={draft.daily_limit} onChange={value => value && change({daily_limit:value})}/></div>
      <div><label htmlFor="proactive-gap">最短间隔（小时）</label><InputNumber id="proactive-gap" min={0} max={168} value={draft.minimum_interval_seconds / 3600} onChange={value => value !== null && change({minimum_interval_seconds:Math.round(value * 3600)})}/></div>
      <div><label htmlFor="proactive-schedule">定时问候时刻</label><Input id="proactive-schedule" type="time" value={minuteText(draft.scheduled_minute)} onChange={event => change({scheduled_minute:parseMinute(event.target.value)})}/></div>
    </div>
    <label htmlFor="proactive-greeting">固定问候内容</label>
    <Input id="proactive-greeting" maxLength={80} showCount value={draft.greeting_text} onChange={event => change({greeting_text:event.target.value})}/>
    {draft.automatic_enabled && !scheduleInsideWindow && <Alert type="error" showIcon title="定时问候时刻必须位于允许时段内"/>}
    <p className="subtle">时区：UTC{draft.utc_offset_minutes >= 0 ? '+' : ''}{draft.utc_offset_minutes / 60}（第一版固定偏移）；消息超过 {draft.maximum_lifetime_seconds / 60} 分钟就不再投递。</p>
    <div className="setting-line"><span>{quietActive ? `临时勿扰至 ${new Date(draft.quiet_until!).toLocaleString()}` : '临时勿扰未开启'}</span><Space><Button onClick={() => change({quiet_until:new Date(Date.now() + 60 * 60 * 1000).toISOString()})}>勿扰 1 小时</Button><Button disabled={!draft.quiet_until} onClick={() => change({quiet_until:null})}>解除勿扰</Button></Space></div>
    <Space><Button type="primary" loading={mutation.isPending} disabled={!dirty || draft.allowed_weekdays.length === 0 || draft.allowed_start_minute === draft.allowed_end_minute || (draft.automatic_enabled && !scheduleInsideWindow) || !draft.greeting_text.trim() || draft.greeting_text !== draft.greeting_text.trim()} onClick={() => mutation.mutate(draft)}>保存主动交流设置</Button><Button disabled={!dirty || mutation.isPending} onClick={() => {setDraft({...query.data!, allowed_weekdays:[...query.data!.allowed_weekdays]}); setNotice('已放弃未保存修改。');}}>放弃修改</Button></Space>
    {notice && <p role="status">{notice}</p>}
    </section>
    <section className="settings-section">
      <h3>手动验证圆屏问候</h3>
      <p className="subtle">每次点击只尝试一次。它由你明确触发，因此不受“等待用户回应”限制；仍遵守总开关、时间段、勿扰、频率和设备忙碌限制，失败不会自动重试。</p>
      <Input aria-label="测试问候内容" maxLength={80} showCount value={testText} onChange={event => setTestText(event.target.value)}/>
      <Button loading={testMutation.isPending} disabled={!draft.enabled || dirty || testMutation.isPending || !testText.trim() || testText !== testText.trim()} onClick={() => testMutation.mutate()}>发送一次测试问候</Button>
      {!draft.enabled && <p className="subtle">请先打开并保存“允许主动联系”，再进行测试。</p>}
      {dirty && <p className="subtle">当前设置尚未保存，请保存或放弃修改后再测试。</p>}
      {testNotice && <p role="status">{testNotice}</p>}
    </section>
    <ProactiveTopicSection
      scenarios={scenarios.data?.items ?? []}
      scenariosLoaded={scenarios.isSuccess}
      seeds={topicSeeds.data?.items ?? []}
      seedsLoaded={topicSeeds.isSuccess}
      scenarioId={topicScenarioId}
      text={topicText}
      notice={topicNotice}
      createPending={createTopic.isPending}
      disablePending={disableTopic.isPending}
      disablingId={disableTopic.variables?.id}
      proactiveEnabled={draft.enabled}
      automaticEnabled={draft.automatic_enabled}
      topicEnabled={draft.topic_enabled}
      onScenarioChange={setTopicScenarioId}
      onTextChange={setTopicText}
      onCreate={() => createTopic.mutate()}
      onDisable={seed => disableTopic.mutate(seed)}
      onTopicEnabledChange={topic_enabled => change({topic_enabled})}
    />
    <ProactiveFollowUpSection
      sources={followUpSources.data?.items ?? []}
      items={followUps.data?.items ?? []}
      loaded={followUps.isSuccess}
      failed={followUps.isError}
      sourceId={followUpSourceId}
      text={followUpText}
      localTime={followUpLocal}
      notice={followUpNotice}
      createPending={createFollowUp.isPending}
      cancelPending={cancelFollowUp.isPending}
      armPending={armFollowUp.isPending}
      cancellingId={cancelFollowUp.variables?.id}
      armingId={armFollowUp.variables?.id}
      proactiveEnabled={draft.enabled}
      policyDirty={dirty}
      onSourceChange={setFollowUpSourceId}
      onTextChange={setFollowUpText}
      onLocalTimeChange={setFollowUpLocal}
      onCreate={() => createFollowUp.mutate()}
      onCancel={item => cancelFollowUp.mutate(item)}
      onArm={item => armFollowUp.mutate(item)}
    />
    <CompanionLearningSection
      strategyItems={strategyCandidates.data?.items ?? []}
      strategyLoaded={strategyCandidates.isSuccess}
      strategyFailed={strategyCandidates.isError}
      strategyNotice={strategyNotice}
      analyzeStrategyPending={analyzeStrategy.isPending}
      dismissStrategyPending={dismissStrategy.isPending}
      dismissingStrategyId={dismissStrategy.variables?.id}
      userItems={userInitiated.data?.items ?? []}
      userLoaded={userInitiated.isSuccess}
      userFailed={userInitiated.isError}
      routineItems={routineCandidates.data?.items ?? []}
      routineLoaded={routineCandidates.isSuccess}
      routineFailed={routineCandidates.isError}
      routineNotice={routineNotice}
      analyzeRoutinePending={analyzeRoutine.isPending}
      dismissRoutinePending={dismissRoutine.isPending}
      dismissingRoutineId={dismissRoutine.variables?.id}
      createVersionPending={createAbsenceVersion.isPending}
      creatingVersionId={createAbsenceVersion.variables?.id}
      versionNotice={absenceVersionNotice}
      versions={absenceVersions.data}
      versionsFailed={absenceVersions.isError}
      switchVersionPending={switchAbsenceVersion.isPending}
      switchingVersionId={switchAbsenceVersion.variables?.version.id}
      deactivatePending={deactivateAbsenceVersion.isPending}
      onAnalyzeStrategy={() => analyzeStrategy.mutate()}
      onDismissStrategy={item => dismissStrategy.mutate(item)}
      onAnalyzeRoutine={() => analyzeRoutine.mutate()}
      onDismissRoutine={item => dismissRoutine.mutate(item)}
      onCreateVersion={item => createAbsenceVersion.mutate(item)}
      onSwitchVersion={(version, rollback) => switchAbsenceVersion.mutate({version, rollback})}
      onDeactivateVersion={() => deactivateAbsenceVersion.mutate()}
    />
    <ProactiveHistorySection
      items={history.data?.items ?? []}
      loading={history.isLoading}
      failed={history.isError}
      confirmingId={confirmMutation.variables?.outreach_id}
      confirmPending={confirmMutation.isPending}
      onConfirm={item => confirmMutation.mutate(item)}
    />
  </Space>;
}
