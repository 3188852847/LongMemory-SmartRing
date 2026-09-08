import {useEffect, useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, Input, InputNumber, Select, Space, Switch, Tag} from 'antd';
import {ApiError, ChatApi, type CompanionAbsenceStrategyVersion, type CompanionAbsenceStrategyVersionList, type CompanionRoutineCandidate, type CompanionStrategyCandidate, type ProactiveOutreachSummary, type ProactivePolicy, type ProactiveScheduleStatus, type ProactiveTestResult, type ProactiveTopicSeed, type UserInitiatedInteraction} from './api';

const DAYS = ['周一','周二','周三','周四','周五','周六','周日'].map((label, value) => ({label, value}));
const minuteText = (value:number) => `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}`;
const parseMinute = (value:string) => {const [hour, minute] = value.split(':').map(Number); return hour * 60 + minute;};
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
    <section className="settings-section">
      <h3>记忆驱动话题素材</h3>
      <Alert type="warning" showIcon title="这里只保存你允许圆屏公开念出的短句"
        description="来源限定为当前有效且已接受的 L2 场景。仅保存素材不会自动投递；还需显式打开并保存下方开关。实际定时投递仍会经过勿扰、频率和设备状态门控。请不要填写不适合被旁人听见的信息。"/>
      <label htmlFor="topic-source">来源 L2 场景</label>
      <Select id="topic-source" aria-label="来源 L2 场景" className="wide" value={topicScenarioId}
        placeholder="选择一个已接受的生活场景" onChange={setTopicScenarioId}
        options={(scenarios.data?.items ?? []).map(item => ({value:item.id,label:item.title}))}/>
      <label htmlFor="topic-text">允许播出的安全话题</label>
      <Input id="topic-text" maxLength={120} showCount value={topicText}
        placeholder="例如：毕业设计汇报准备得怎么样了？"
        onChange={event => setTopicText(event.target.value)}/>
      <Button loading={createTopic.isPending}
        disabled={!topicScenarioId || !topicText.trim() || topicText !== topicText.trim() || createTopic.isPending}
        onClick={() => createTopic.mutate()}>保存为话题素材</Button>
      {scenarios.isSuccess && (scenarios.data?.items?.length ?? 0) === 0 && <p className="subtle">还没有当前有效且已接受的 L2 场景；请先在“生活场景”页建立并接受场景。</p>}
      {topicNotice && <p role="status">{topicNotice}</p>}
      <div className="proactive-history">{topicSeeds.data?.items?.map(seed => <Card size="small" key={seed.id}
        title={<Space wrap><Tag color={seed.usable ? 'green' : 'default'}>{seed.usable ? '可用' : '不可用'}</Tag><span>{seed.prompt_text}</span></Space>}
        extra={seed.status === 'active' && <Button size="small" danger disabled={disableTopic.isPending}
          loading={disableTopic.isPending && disableTopic.variables?.id === seed.id}
          onClick={() => disableTopic.mutate(seed)}>停用</Button>}>
        <p className="subtle">来源 L2：{seed.source.title} · {seed.source.status} · 修订 {seed.revision}</p>
        <p>{seed.source.summary}</p>
        <small>素材 ID：{seed.id} · 来源 ID：{seed.scenario_id}</small>
      </Card>)}</div>
      {topicSeeds.isSuccess && (topicSeeds.data?.items?.length ?? 0) === 0 && <p className="subtle">尚无话题素材。</p>}
      <div className="setting-line"><span>定时问候优先使用可用话题素材</span><Switch
        aria-label="优先使用记忆话题" disabled={!draft.enabled || !draft.automatic_enabled}
        checked={draft.topic_enabled} onChange={topic_enabled => change({topic_enabled})}/></div>
      <p className="subtle">此开关默认关闭。开启并保存后，定时点会从可用素材中优先选择最久未使用的一条；没有可用素材时仍使用上方固定问候。</p>
    </section>
    <section className="settings-section">
      <h3>联系时段观察候选</h3>
      <Alert type="info" showIcon title="候选不会自动生效"
        description="系统只检查时间关系：至少三个不同日期、同一半小时区间内，正式问候后 30 分钟内出现用户消息，才提出一个值得试验的时刻。它不能证明你喜欢该时段，也不会写入 L3 用户画像。"/>
      <Button loading={analyzeStrategy.isPending} disabled={analyzeStrategy.isPending}
        onClick={() => analyzeStrategy.mutate()}>分析现有互动记录</Button>
      {strategyNotice && <p role="status">{strategyNotice}</p>}
      {strategyCandidates.isError && <Alert type="error" showIcon title="策略候选读取失败"/>}
      <div className="proactive-history">{strategyCandidates.data?.items?.map(candidate => <Card size="small" key={candidate.id}
        title={<Space wrap><Tag color={candidate.status === 'candidate' ? 'gold' : 'default'}>{candidate.status === 'candidate' ? '待观察' : '已忽略'}</Tag><strong>建议试验 {minuteText(candidate.suggested_minute)}</strong><Tag>未生效</Tag></Space>}
        extra={candidate.status === 'candidate' && <Button size="small" danger
          loading={dismissStrategy.isPending && dismissStrategy.variables?.id === candidate.id}
          disabled={dismissStrategy.isPending}
          onClick={() => dismissStrategy.mutate(candidate)}>忽略候选</Button>}>
        <p>来自 {candidate.distinct_local_dates} 个不同日期的 {candidate.evidence_count} 条时间观察。</p>
        <p className="subtle">这只是“问候后出现了消息”的时间共现，不表示因果、满意或时间偏好。</p>
        {candidate.sources.map(source => <p className="subtle" key={source.interaction_event_id}>
          {source.local_date} {minuteText(source.local_minute)} · {Math.round(source.latency_seconds / 60)} 分钟后出现用户消息 · 投递证据 {source.delivery_evidence_level}
        </p>)}
        <small>生成器：{candidate.generator_version} · 候选 ID：{candidate.id}</small>
      </Card>)}</div>
      {strategyCandidates.isSuccess && (strategyCandidates.data?.items?.length ?? 0) === 0 && <p className="subtle">尚无联系时段候选。</p>}
      <h4>用户主动出现时间观察</h4>
      <p className="subtle">当前只把“距离上一条用户消息至少 4 小时，且此前 30 分钟没有主动问候”的消息记作一次观察。它是可审计的时间启发式，不等同于真实会话边界，也不会保存或展示消息正文。</p>
      {userInitiated.isError && <Alert type="error" showIcon title="主动出现记录读取失败"/>}
      <div className="proactive-history">{userInitiated.data?.items?.map(item => <Card size="small" key={item.id}>
        <p><strong>{item.local_date} {minuteText(item.local_minute)}</strong></p>
        <p className="subtle">{item.silence_gap_seconds === null ? '第一条可观察用户消息' : `此前静默约 ${Math.round(item.silence_gap_seconds / 3600 * 10) / 10} 小时`} · 近期无主动问候</p>
        <small>检测器：{item.detector_version} · 来源消息 ID：{item.source_message_id}</small>
      </Card>)}</div>
      {userInitiated.isSuccess && (userInitiated.data?.items?.length ?? 0) === 0 && <p className="subtle">尚无用户主动出现时间观察。</p>}
      <h4>可能的日常交流时段</h4>
      <p className="subtle">至少三个不同日期在同一半小时区间主动出现，才会形成弱习惯候选。候选只表示重复时间规律；某天没出现不等于需要帮助，也不会自动触发问候。</p>
      <Button loading={analyzeRoutine.isPending} disabled={analyzeRoutine.isPending}
        onClick={() => analyzeRoutine.mutate()}>分析主动出现规律</Button>
      {routineNotice && <p role="status">{routineNotice}</p>}
      {routineCandidates.isError && <Alert type="error" showIcon title="主动出现时段候选读取失败"/>}
      <div className="proactive-history">{routineCandidates.data?.items?.map(candidate => <Card size="small" key={candidate.id}
        title={<Space wrap><Tag color={candidate.status === 'candidate' ? 'gold' : 'default'}>{candidate.status === 'candidate' ? '待观察' : '已忽略'}</Tag><strong>常在 {minuteText(candidate.expected_minute)} 左右主动出现</strong><Tag>未生效</Tag></Space>}
        extra={candidate.status === 'candidate' && <Space><Button size="small"
          loading={createAbsenceVersion.isPending && createAbsenceVersion.variables?.id === candidate.id}
          disabled={createAbsenceVersion.isPending}
          onClick={() => createAbsenceVersion.mutate(candidate)}>生成离线验证草案</Button><Button size="small" danger
            loading={dismissRoutine.isPending && dismissRoutine.variables?.id === candidate.id}
            disabled={dismissRoutine.isPending}
            onClick={() => dismissRoutine.mutate(candidate)}>忽略候选</Button></Space>}>
        <p>来自 {candidate.distinct_local_dates} 个不同日期的 {candidate.evidence_count} 条主动出现观察。</p>
        <p className="subtle">这不是主动联系规则，也没有定义“缺席后多久问候”。</p>
        {candidate.sources.map(source => <p className="subtle" key={source.user_initiated_event_id}>
          {source.local_date} {minuteText(source.local_minute)} · {source.silence_gap_seconds === null ? '首条观察' : `此前静默约 ${Math.round(source.silence_gap_seconds / 3600 * 10) / 10} 小时`}
        </p>)}
        <small>生成器：{candidate.generator_version} · 候选 ID：{candidate.id}</small>
      </Card>)}</div>
      {routineCandidates.isSuccess && (routineCandidates.data?.items?.length ?? 0) === 0 && <p className="subtle">尚无主动出现时段候选。</p>}
      {absenceVersionNotice && <p role="status">{absenceVersionNotice}</p>}
      {absenceVersions.isError && <Alert type="error" showIcon title="离线验证草案读取失败"/>}
      <h4>缺席联系策略版本</h4>
      <p className="subtle">当前版本会在常见时段加上宽限后的唯一分钟参与后台检查；错过不补发，并继续遵守主动交流总开关、勿扰、频率、待回应、会话和设备门控。</p>
      <div className="proactive-history">{absenceVersions.data?.items?.map(version => <Card size="small" key={version.id}
        title={<Space wrap><Tag color={version.replay_gate_passed ? 'green' : 'red'}>{version.replay_gate_passed ? '离线门控通过' : '离线门控未通过'}</Tag><strong>{minuteText(version.expected_minute)} 后宽限 {version.grace_minutes} 分钟</strong><Tag color={version.active ? 'blue' : 'default'}>{version.active ? '当前版本' : '非当前版本'}</Tag></Space>}
        extra={version.active ? <Button size="small" danger loading={deactivateAbsenceVersion.isPending}
          onClick={() => deactivateAbsenceVersion.mutate()}>停用</Button> : <Button size="small" type="primary"
          disabled={!version.replay_gate_passed || switchAbsenceVersion.isPending}
          loading={switchAbsenceVersion.isPending && switchAbsenceVersion.variables?.version.id === version.id}
          onClick={() => switchAbsenceVersion.mutate({version, rollback:Boolean(absenceVersions.data?.events?.some(event => event.selected_version_id === version.id))})}>
          {absenceVersions.data?.events?.some(event => event.selected_version_id === version.id) ? '回滚到此版本' : '设为当前版本'}
        </Button>}>
        <p>回放匹配 {version.replay_matched_count}/{version.replay_case_count}；不安全放行 {version.replay_unsafe_allow_count}。</p>
        <p className="subtle">数据集：{version.replay_dataset_name} {version.replay_dataset_version} · 协议 {version.replay_protocol}</p>
        <small>SHA-256：{version.replay_dataset_sha256} · 来源候选：{version.source_candidate_id} 修订 {version.source_candidate_revision}</small>
      </Card>)}</div>
      {absenceVersions.isSuccess && (absenceVersions.data?.items?.length ?? 0) === 0 && <p className="subtle">尚无离线验证草案。</p>}
      {(absenceVersions.data?.events?.length ?? 0) > 0 && <>
        <h4>版本切换记录</h4>
        {absenceVersions.data!.events!.map(event => <p className="subtle" key={event.id}>
          修订 {event.pointer_revision} · {event.action} · {new Date(event.created_at).toLocaleString()} · {event.previous_version_id ?? '无'} → {event.selected_version_id ?? '停用'}
        </p>)}
      </>}
    </section>
    <section className="settings-section">
      <h3>最近运行记录</h3>
      <p className="subtle">这里展示真实账本状态；排队、设备确认和播放是不同证据级别。</p>
      {history.isError && <Alert type="error" showIcon title="运行记录读取失败"/>}
      {history.isLoading && <p className="subtle">正在读取运行记录…</p>}
      {!history.isLoading && (history.data?.items?.length ?? 0) === 0 && <p className="subtle">还没有主动交流记录。</p>}
      <div className="proactive-history">{history.data?.items?.map(item => <article className="proactive-history-item" key={item.outreach_id}>
        <div className="setting-line"><Space><Tag>{item.state}</Tag><strong>{item.content}</strong></Space>
          {['queued','transport_sent','device_acknowledged'].includes(item.state) && <Button size="small" loading={confirmMutation.isPending && confirmMutation.variables?.outreach_id === item.outreach_id} disabled={confirmMutation.isPending} onClick={() => confirmMutation.mutate(item)}>确认已听到</Button>}
        </div>
        <p className="subtle">{new Date(item.created_at).toLocaleString()} · 原因 {item.reason} · {item.event_count} 个事件</p>
        {item.topic_seed_id && <p className="subtle">记忆话题来源：{item.topic_seed_id} · 素材修订 {item.topic_seed_revision}</p>}
        {item.strategy_source && <p className="subtle">
          习惯策略来源：版本 {item.strategy_source.version_id} · 激活修订 {item.strategy_source.selection_revision} · 来源候选 {item.strategy_source.source_candidate_id} 修订 {item.strategy_source.source_candidate_revision}<br/>
          {item.strategy_source.evaluated_local_date} 在 {String(Math.floor((item.strategy_source.expected_minute + item.strategy_source.grace_minutes) / 60)).padStart(2,'0')}:{String((item.strategy_source.expected_minute + item.strategy_source.grace_minutes) % 60).padStart(2,'0')} 检查 · 触发器 {item.strategy_source.trigger_policy_version}
        </p>}
        {item.outcome_observation_state === 'subsequent_user_message_observed' && item.subsequent_user_message && <p className="subtle">
          后续用户消息：已观察（{Math.round(item.subsequent_user_message.latency_seconds / 60)} 分钟后；仅表示时间先后）
        </p>}
        {item.outcome_observation_state === 'awaiting_subsequent_user_message' && <p className="subtle">
          后续用户消息：尚未观察（投递证据：{item.delivery_evidence_level}）
        </p>}
        {item.outcome_observation_state === 'delivery_not_established' && <p className="subtle">
          互动观察：投递未成立，不能解释为用户未回应
        </p>}
        {item.explicit_feedback && <p className="subtle">
          明确反馈：用户拒绝继续使用该话题，素材已停用（用户明确陈述）
        </p>}
      </article>)}</div>
    </section>
  </Space>;
}
