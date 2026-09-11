import {useEffect, useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Space} from 'antd';
import {ApiError, ChatApi, type CompanionAbsenceStrategyVersion, type CompanionAbsenceStrategyVersionList, type CompanionRoutineCandidate, type CompanionStrategyCandidate, type FollowUpCandidate, type ProactiveOutreachSummary, type ProactivePolicy, type ProactiveScheduleStatus, type ProactiveTestResult, type ProactiveTopicSeed, type UserInitiatedInteraction} from './api';
import {ProactiveHistorySection} from './ProactiveHistorySection';
import {ProactiveTopicSection} from './ProactiveTopicSection';
import {ProactiveFollowUpSection} from './ProactiveFollowUpSection';
import {CompanionLearningSection} from './CompanionLearningSection';
import {ProactivePolicySection} from './ProactivePolicySection';


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
  return <Space className="proactive-settings" orientation="vertical" style={{width:'100%'}}>
    <ProactivePolicySection
      draft={draft}
      dirty={dirty}
      notice={notice}
      schedule={scheduleStatus.data}
      scheduleFailed={scheduleStatus.isError}
      savePending={mutation.isPending}
      armPending={armScheduleTest.isPending}
      cancelPending={cancelScheduleTest.isPending}
      testText={testText}
      testNotice={testNotice}
      testPending={testMutation.isPending}
      onChange={change}
      onSave={() => mutation.mutate(draft)}
      onDiscard={() => {setDraft({...query.data!, allowed_weekdays:[...query.data!.allowed_weekdays]}); setNotice('已放弃未保存修改。');}}
      onArm={() => armScheduleTest.mutate()}
      onCancel={() => cancelScheduleTest.mutate()}
      onTestText={setTestText}
      onTest={() => testMutation.mutate()}
    />
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
