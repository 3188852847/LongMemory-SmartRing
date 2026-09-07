import {useEffect, useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, Input, InputNumber, Select, Space, Switch, Tag} from 'antd';
import {ApiError, ChatApi, type ProactiveOutreachSummary, type ProactivePolicy, type ProactiveTestResult, type ProactiveTopicSeed} from './api';

const DAYS = ['周一','周二','周三','周四','周五','周六','周日'].map((label, value) => ({label, value}));
const minuteText = (value:number) => `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}`;
const parseMinute = (value:string) => {const [hour, minute] = value.split(':').map(Number); return hour * 60 + minute;};

/** 编辑明确许可边界；保存设置不会调用模型、创建候选或向设备投递。 */
export function ProactiveSettings({api, ready}:{api:ChatApi; ready:boolean}) {
  const client = useQueryClient();
  const query = useQuery({queryKey:['proactive-policy'], queryFn:() => api.request<ProactivePolicy>('/api/proactive-policy'), enabled:ready});
  const history = useQuery({queryKey:['proactive-outreach'], queryFn:() => api.request<{items:ProactiveOutreachSummary[]}>('/api/proactive-outreach?limit=10'), enabled:ready});
  const scenarios = useQuery({queryKey:['proactive-topic-scenarios'], queryFn:() => api.request<{items:Array<{id:string;title:string;summary:string;revision:number}>}>('/api/scenarios?state=active&offset=0&limit=100'), enabled:ready});
  const topicSeeds = useQuery({queryKey:['proactive-topic-seeds'], queryFn:() => api.request<{items:ProactiveTopicSeed[]}>('/api/proactive-topic-seeds'), enabled:ready});
  const [draft, setDraft] = useState<ProactivePolicy>();
  const [notice, setNotice] = useState('');
  const [testText, setTestText] = useState('今天也要照顾好自己呀。');
  const [testNotice, setTestNotice] = useState('');
  const [topicScenarioId, setTopicScenarioId] = useState<string>();
  const [topicText, setTopicText] = useState('');
  const [topicNotice, setTopicNotice] = useState('');
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
      greeting_text:value.greeting_text,
    }),
    onSuccess:value => {client.setQueryData(['proactive-policy'], value); setDraft({...value, allowed_weekdays:[...value.allowed_weekdays]}); setNotice(value.automatic_enabled ? '设置已保存；后台只会在指定分钟检查一次。' : '设置已保存；后台定时问候保持关闭。');},
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
      setTopicNotice('安全话题素材已保存；当前只供预览，不会自动播报。');
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
  const change = (patch:Partial<ProactivePolicy>) => draft && setDraft({...draft, ...patch});
  if (query.isError) return <Alert type="error" showIcon title="主动交流设置不可用" description="请确认已选择当前版本的个人数据库。"/>;
  if (query.isLoading || !draft) return <Alert type="info" showIcon title="正在读取主动交流设置…"/>;
  const quietActive = draft.quiet_until && new Date(draft.quiet_until).getTime() > Date.now();
  const scheduleInsideWindow = draft.allowed_start_minute < draft.allowed_end_minute
    ? draft.scheduled_minute >= draft.allowed_start_minute && draft.scheduled_minute < draft.allowed_end_minute
    : draft.scheduled_minute >= draft.allowed_start_minute || draft.scheduled_minute < draft.allowed_end_minute;
  return <Space orientation="vertical" style={{width:'100%'}}>
    <Alert type={draft.automatic_enabled ? 'warning' : 'success'} showIcon
      title={draft.automatic_enabled ? '后台定时问候已开启' : (draft.enabled ? '主动联系许可已打开，定时问候仍关闭' : '主动交流当前关闭')}
      description="定时问候只在所选星期的指定分钟检查：当天已经聊过、设备离线或忙碌、处于勿扰或错过时刻都会跳过，之后不补发。"/>
    <div className="setting-line"><span>允许主动联系</span><Switch aria-label="允许主动联系" checked={draft.enabled} onChange={enabled => change({enabled, ...(!enabled ? {automatic_enabled:false} : {})})}/></div>
    <div className="setting-line"><span>后台定时问候</span><Switch aria-label="后台定时问候" disabled={!draft.enabled} checked={draft.automatic_enabled} onChange={automatic_enabled => change({automatic_enabled})}/></div>
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
    <section className="settings-section">
      <h3>手动验证圆屏问候</h3>
      <p className="subtle">每次点击只尝试一次，仍遵守总开关、时间段、勿扰、频率和设备忙碌限制；失败不会自动重试。</p>
      <Input aria-label="测试问候内容" maxLength={80} showCount value={testText} onChange={event => setTestText(event.target.value)}/>
      <Button loading={testMutation.isPending} disabled={!draft.enabled || dirty || testMutation.isPending || !testText.trim() || testText !== testText.trim()} onClick={() => testMutation.mutate()}>发送一次测试问候</Button>
      {!draft.enabled && <p className="subtle">请先打开并保存“允许主动联系”，再进行测试。</p>}
      {dirty && <p className="subtle">当前设置尚未保存，请保存或放弃修改后再测试。</p>}
      {testNotice && <p role="status">{testNotice}</p>}
    </section>
    <section className="settings-section">
      <h3>记忆驱动话题素材（预览阶段）</h3>
      <Alert type="warning" showIcon title="这里只保存你允许圆屏公开念出的短句"
        description="来源限定为当前有效且已接受的 L2 场景。保存后不会自动投递；后续接入定时器前仍会经过勿扰、频率和设备状态门控。请不要填写不适合被旁人听见的信息。"/>
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
      </article>)}</div>
    </section>
  </Space>;
}
