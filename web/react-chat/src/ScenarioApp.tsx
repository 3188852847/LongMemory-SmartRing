import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, Descriptions, Drawer, Empty, Input, List, Modal, Select, Space, Tag} from 'antd';
import {useSearchParams} from 'react-router-dom';
import {ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {ConsolidationStatusCard} from './ConsolidationStatusCard';
import {derivedMemoryFailure} from './derivedMemoryFailure';

type ScenarioState = 'candidate' | 'active' | 'rejected' | 'stale';
type MemoryConfig = {configured: boolean; database: string | null; allow_scenario_management: boolean;
  scenario_model_preview_available: boolean; scenario_model: string | null};
type L1 = {id: string; content: string; subject_id: string; state: 'active' | 'retired'};
type Scenario = {
  id: string; subject_id: string; title: string; summary: string; generated_at: string;
  valid_from: string | null; valid_to: string | null; status: ScenarioState;
  generator_name: string; generator_version: string; revision: number;
};
type ScenarioSource = {
  memory_id: string; memory_content_snapshot: string; linked_at: string;
  current_content: string | null; retired_at: string | null;
  l0_sources: Array<{source_message_id: string; source_type: string; linked_at: string; role: string | null; content: string | null; created_at: string | null}>;
};
type ScenarioLifecycleEvent = {id:string; action:'manual_end'|'source_retired'|'source_deleted'; actor_type:'user'|'system'; occurred_at:string; previous_status:string; new_status:string; scenario_revision:number};
type ScenarioDetail = Scenario & {sources: ScenarioSource[]; lifecycle_events: ScenarioLifecycleEvent[]};
type Page<T> = {items: T[]; total: number; limit: number; offset: number};
type ScenarioProposal = {title: string; summary: string; source_memory_ids: string[];
  generator_name: string; generator_version: string; model: string | null; persisted: false};
type SourceInbox = {items: Array<{id:string;content:string;subject_id:string;recorded_at:string;source_message_count:number}>; total:number;
  limited:boolean; selection_is_semantic:false};

const api = new ChatApi();
const stateName: Record<ScenarioState, string> = {candidate: '待复核', active: '已接受', rejected: '已拒绝', stale: '已失效'};
const stateColor: Record<ScenarioState, string> = {candidate: 'gold', active: 'green', rejected: 'default', stale: 'red'};
const displayTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未记录';

/** L2 是多条 L1 汇总出的生活场景；候选可带现实有效期，回答使用由独立开关控制。 */
export function ScenarioApp() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState('正在连接本机记忆服务…');
  const [filter, setFilter] = useState<'all' | ScenarioState>('all');
  const [selectedId, setSelectedId] = useState<string|undefined>(() => {
    const value = searchParams.get('scenario_id')?.trim();
    return value && value.length <= 128 && !/[\u0000-\u001f\u007f]/.test(value) ? value : undefined;
  });
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [validFrom, setValidFrom] = useState('');
  const [validTo, setValidTo] = useState('');
  const [draftOrigin, setDraftOrigin] = useState<'manual' | 'model_assisted'>('manual');
  const [confirmingModel, setConfirmingModel] = useState(false);
  const [previewMode, setPreviewMode] = useState<'selected' | 'inbox'>('selected');
  const [reviewDecision, setReviewDecision] = useState<'accepted' | 'rejected'>();
  const [ending, setEnding] = useState(false);
  const [inboxOnly, setInboxOnly] = useState(false);

  useEffect(() => {void api.bootstrap().then(() => setReady(true)).catch(error => setNotice(derivedMemoryFailure(error, 'read')));}, []);
  const config = useQuery({queryKey: ['memory-config'], enabled: ready,
    queryFn: () => api.request<MemoryConfig>('/api/memory-config')});
  const scenarios = useQuery({queryKey: ['scenarios', filter], enabled: ready && config.data?.configured === true,
    queryFn: () => api.request<Page<Scenario>>(`/api/scenarios?state=${filter}&offset=0&limit=100`)});
  const memories = useQuery({queryKey: ['scenario-source-l1'], enabled: ready && config.data?.configured === true,
    queryFn: () => api.request<Page<L1>>('/api/memories?state=active&q=&offset=0&limit=100')});
  const sourceInbox = useQuery({queryKey: ['scenario-source-inbox'], enabled: ready && config.data?.configured === true,
    queryFn: () => api.request<SourceInbox>('/api/scenario-source-inbox')});
  const detail = useQuery({queryKey: ['scenario', selectedId], enabled: ready && Boolean(selectedId),
    queryFn: () => api.request<ScenarioDetail>(`/api/scenarios/${encodeURIComponent(selectedId!)}`)});
  const closeDetail = () => {
    setSelectedId(undefined);
    if (searchParams.has('scenario_id')) {
      const next = new URLSearchParams(searchParams); next.delete('scenario_id'); setSearchParams(next, {replace:true});
    }
  };

  const createCandidate = useMutation({
    mutationFn: () => api.request<{id: string}>('/api/scenarios', 'POST', {
      title: title.trim(), summary: summary.trim(), source_memory_ids: sourceIds,
      creation_kind: draftOrigin, confirm_candidate: true,
      valid_from: validFrom ? new Date(validFrom).toISOString() : null,
      valid_to: validTo ? new Date(validTo).toISOString() : null,
    }),
    onSuccess: async result => {
      setCreating(false); setTitle(''); setSummary(''); setSourceIds([]); setValidFrom(''); setValidTo(''); setDraftOrigin('manual'); setSelectedId(result.id);
      await queryClient.invalidateQueries({queryKey: ['scenarios']});
      await queryClient.invalidateQueries({queryKey: ['scenario-source-inbox']});
      setNotice('L2 候选已创建，尚未进入已接受状态。');
    },
    onError: error => setNotice(derivedMemoryFailure(error, 'write')),
  });
  const previewCandidate = useMutation({
    mutationFn: () => api.request<ScenarioProposal>('/api/scenario-proposals', 'POST', {
      source_memory_ids: sourceIds, confirm_model_call: true,
    }),
    onSuccess: proposal => {
      setConfirmingModel(false);
      setTitle(proposal.title); setSummary(proposal.summary);
      setSourceIds(proposal.source_memory_ids); setDraftOrigin('model_assisted');
      setNotice(`模型草稿已返回（${proposal.model ?? '未标记模型'}），尚未写入数据库；请核对和修改后再创建候选。`);
    },
    onError: error => {setConfirmingModel(false); setNotice(derivedMemoryFailure(error, 'preview'));},
  });
  const review = useMutation({
    mutationFn: (decision: 'accepted' | 'rejected') => api.request(`/api/scenarios/${encodeURIComponent(selectedId!)}/reviews`, 'POST', {
      decision, expected_revision: detail.data!.revision, confirm_review: true,
    }),
    onSuccess: async () => {
      setReviewDecision(undefined);
      await Promise.all([
        queryClient.invalidateQueries({queryKey: ['scenarios']}),
        queryClient.invalidateQueries({queryKey: ['scenario', selectedId]}),
      ]);
      setNotice('复核结果已保存；只有另行开启 L2 使用且问题相关时才会参与回答。');
    },
    onError: error => setNotice(derivedMemoryFailure(error, 'write')),
  });
  const endScenario = useMutation({
    mutationFn: () => api.request(`/api/scenarios/${encodeURIComponent(selectedId!)}/lifecycle`, 'POST', {
      action: 'manual_end', expected_revision: detail.data!.revision, confirm_action: true,
    }),
    onSuccess: async () => {
      setEnding(false);
      await Promise.all([
        queryClient.invalidateQueries({queryKey: ['scenarios']}),
        queryClient.invalidateQueries({queryKey: ['scenario', selectedId]}),
      ]);
      setNotice('场景已结束并保留生命周期记录；后续回答不会再召回它。');
    },
    onError: error => {setEnding(false); setNotice(derivedMemoryFailure(error, 'write'));},
  });
  const busy = config.isFetching || scenarios.isFetching || memories.isFetching || sourceInbox.isFetching || detail.isFetching || createCandidate.isPending || previewCandidate.isPending || review.isPending || endScenario.isPending;
  const canManage = config.data?.allow_scenario_management === true;
  const openCreator = () => {setTitle(''); setSummary(''); setSourceIds([]); setValidFrom(''); setValidTo(''); setDraftOrigin('manual'); setInboxOnly(false); setCreating(true);};
  const inboxIds = new Set((sourceInbox.data?.items ?? []).map(item => item.id));
  const sourceOptions = (memories.data?.items ?? [])
    .filter(item => !inboxOnly || inboxIds.has(item.id))
    .sort((left, right) => Number(inboxIds.has(right.id)) - Number(inboxIds.has(left.id)))
    .map(item => ({value:item.id,label:`${inboxIds.has(item.id) ? '待整理 · ' : ''}${item.content}`}));
  const recommendFromInbox = () => {
    setTitle(''); setSummary(''); setValidFrom(''); setValidTo(''); setDraftOrigin('manual');
    setInboxOnly(true); setSourceIds((sourceInbox.data?.items ?? []).slice(0, 20).map(item => item.id));
    setCreating(true); setPreviewMode('inbox'); setConfirmingModel(true);
  };
  const sidebar = <><Space direction="vertical" className="wide">
      <Button type="primary" block disabled={!canManage} onClick={openCreator}>新建 L2 候选</Button>
      <Button block disabled={!canManage || !config.data?.scenario_model_preview_available || (sourceInbox.data?.total ?? 0) < 2}
        onClick={recommendFromInbox}>从待整理 L1 推荐一个草稿</Button>
    </Space>
    <ConsoleNav active="scenarios" legacyPath="/memories"/></>;

  return <><AppShell subtitle="可复核的生活场景" className="scenario-shell" sidebar={sidebar}>
    <PageHeader eyebrow="长期记忆" title="生活场景（L2）" description="把多条相关的原子记忆整理成可复核的生活场景；候选不会自动生效。" meta={config.data?.database ?? '未指定记忆库'} action={<Button loading={busy} onClick={() => void queryClient.invalidateQueries({queryKey: ['scenarios']})}>刷新</Button>}/>
    <Alert className="mode-card" type="info" showIcon title="L2 先复核，再按需用于回答"
      description="L2 把多条 L1 汇总成可带现实有效期的生活场景。接受本身不会自动开启使用；回答开关在记忆管理页，且只召回相关的当前场景。"/>
    <ConsolidationStatusCard stage="l1_to_l2" enabled={ready&&config.data?.configured===true}/>
    {!canManage && config.data?.configured && <Alert type="warning" showIcon title="当前进程没有开启 L2 管理权限" description="通过日常启动面板启动时会开启；只读浏览仍可使用。"/>}
    <div className="scenario-toolbar"><Select aria-label="场景状态" value={filter} onChange={value => setFilter(value)} options={[
      {value:'all',label:'全部状态'}, {value:'candidate',label:'待复核'}, {value:'active',label:'已接受'},
      {value:'rejected',label:'已拒绝'}, {value:'stale',label:'已失效'},
    ]}/></div>
    <List loading={scenarios.isFetching} dataSource={scenarios.data?.items ?? []} locale={{emptyText:<Empty description="尚无 L2 生活场景"/>}}
      renderItem={item => <List.Item className="memory-item" onClick={() => setSelectedId(item.id)} actions={[<Button key="open" type="link">查看来源</Button>]}
        ><List.Item.Meta title={<Space wrap><span>{item.title}</span><Tag color={stateColor[item.status]}>{stateName[item.status]}</Tag></Space>}
          description={<><p className="scenario-summary">{item.summary}</p><small>{displayTime(item.generated_at)} · 修订 {item.revision}</small></>}/></List.Item>}/>
    <p role="status">{config.error ? derivedMemoryFailure(config.error, 'read') : scenarios.error ? derivedMemoryFailure(scenarios.error, 'read') : notice}</p>
  </AppShell>

  <Drawer title="L2 场景详情" size="large" open={Boolean(selectedId)} onClose={closeDetail} loading={detail.isFetching}>
    {detail.isError && <Alert type="error" showIcon title="无法打开这条 L2 场景" description="记录可能已经失效、被移除，或记忆服务暂不可用。关闭详情后可刷新场景列表；页面没有自动重试或修改数据。"/>}
    {detail.data && <><Space wrap><h2>{detail.data.title}</h2><Tag color={stateColor[detail.data.status]}>{stateName[detail.data.status]}</Tag></Space>
      <p className="detail-content">{detail.data.summary}</p>
      <Descriptions column={1} size="small" bordered items={[
        {key:'subject',label:'主体',children:detail.data.subject_id}, {key:'generated',label:'生成时间',children:displayTime(detail.data.generated_at)},
        {key:'generator',label:'生成方式',children:`${detail.data.generator_name} ${detail.data.generator_version}`},
        {key:'validFrom',label:'现实开始时间',children:displayTime(detail.data.valid_from)},
        {key:'validTo',label:'现实结束时间',children:displayTime(detail.data.valid_to)},
        {key:'revision',label:'修订号',children:String(detail.data.revision)},
      ]}/>
      <h3>构成此场景的 L1 来源</h3>{detail.data.sources.map(source => <Card className="source-card" key={source.memory_id} size="small" title={source.memory_id}
        extra={<Tag color={source.retired_at ? 'red' : 'green'}>{source.retired_at ? '已退役' : '仍活跃'}</Tag>}>
        <p>{source.memory_content_snapshot}</p>{source.current_content !== source.memory_content_snapshot && <p className="memory-warning">当前 L1 内容与创建时快照不同：{source.current_content ?? '来源已不存在'}</p>}
        <details><summary>查看 L0 原话（{source.l0_sources.length}）</summary>{source.l0_sources.map(item => <blockquote key={`${item.source_message_id}-${item.source_type}`}>
          <p>{item.content ?? '原始记录已不存在'}</p><small>{item.source_type} · {displayTime(item.created_at)}</small>
        </blockquote>)}</details>
      </Card>)}
      {detail.data.status === 'candidate' && <Space><Button type="primary" disabled={!canManage} loading={review.isPending}
        onClick={() => setReviewDecision('accepted')}>接受</Button>
        <Button danger disabled={!canManage} loading={review.isPending}
          onClick={() => setReviewDecision('rejected')}>拒绝</Button></Space>}
      {detail.data.status === 'active' && <Button danger disabled={!canManage} onClick={() => setEnding(true)}>结束场景</Button>}
      <h3>生命周期记录</h3>{detail.data.lifecycle_events.length
        ? <List size="small" dataSource={detail.data.lifecycle_events} renderItem={event => <List.Item>
            <span>{event.action === 'manual_end' ? '用户手动结束' : event.action === 'source_retired' ? '来源 L1 退役' : '来源 L1 删除'} · {displayTime(event.occurred_at)} · 修订 {event.scenario_revision}</span>
          </List.Item>}/>
        : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无生命周期事件"/>}
    </>}
  </Drawer>

  <Modal title="确认结束这个 L2 场景" open={ending} centered width={560}
    confirmLoading={endScenario.isPending} okText="确认结束" cancelText="取消"
    okButtonProps={{danger:true}} onCancel={() => !endScenario.isPending && setEnding(false)}
    onOk={() => endScenario.mutate()}>
    <p><strong>{detail.data?.title ?? '当前场景'}</strong></p>
    <p>结束后状态变为“已失效”，不会再参与网页或圆屏回答。场景内容、L1/L0 来源和本次操作记录都会保留。</p>
  </Modal>

  <Modal title={reviewDecision === 'accepted' ? '确认接受 L2 场景' : '确认拒绝 L2 候选'}
    open={Boolean(reviewDecision)} centered width={560} zIndex={1300}
    confirmLoading={review.isPending} okText={reviewDecision === 'accepted' ? '确认接受' : '确认拒绝'} cancelText="返回核对"
    okButtonProps={{danger: reviewDecision === 'rejected'}} onCancel={() => !review.isPending && setReviewDecision(undefined)}
    onOk={() => reviewDecision && review.mutateAsync(reviewDecision)}>
    <p><strong>{detail.data?.title ?? '当前场景'}</strong></p>
    <p>{reviewDecision === 'accepted'
      ? '接受只改变复核状态。只有另行打开 L2 使用开关，并且问题相关、当前处于有效期时，它才可能参与网页或圆屏回答。'
      : '拒绝后候选会保留用于来源审计，不会物理删除。'}</p>
    <p>请确认已经核对上方详情中的 L1 内容与 L0 原话。</p>
  </Modal>

  <Modal title="确认发送所选 L1 给学校模型" open={confirmingModel} centered width={600} zIndex={1300}
    confirmLoading={previewCandidate.isPending} okText="生成不落库草稿" cancelText="取消"
    onCancel={() => !previewCandidate.isPending && setConfirmingModel(false)}
    onOk={() => previewCandidate.mutate()}>
    <p>本次会把你明确选择的 {sourceIds.length} 条 L1 记忆发送给当前学校模型，用于生成一个 L2 草稿。</p>
    {previewMode === 'inbox' && <p>模型可以只选其中相关的子集；如果找不到至少两条共同支持同一场景的记忆，应拒绝生成，而不是强行合并。</p>}
    <p>模型只调用一次，不自动重试；返回内容不会自动写入数据库，也不会进入聊天回答。</p>
    <p>当前模型：{config.data?.scenario_model ?? '未标记'}</p>
  </Modal>

  <Modal title="新建 L2 候选" open={creating} confirmLoading={createCandidate.isPending} okText="创建待复核候选" cancelText="取消"
    okButtonProps={{disabled: !title.trim() || !summary.trim() || sourceIds.length < 2 || Boolean(validFrom && validTo && new Date(validTo) < new Date(validFrom))}}
    onCancel={() => setCreating(false)} onOk={() => createCandidate.mutate()}>
    <p>至少选择两条同一主体、来源可追溯的活跃 L1。模型只能生成草稿，不会自动保存或接受。</p>
    <label htmlFor="scenario-title">场景标题</label><Input id="scenario-title" value={title} maxLength={120} onChange={event => setTitle(event.target.value)}/>
    <label htmlFor="scenario-summary">场景总结</label><Input.TextArea id="scenario-summary" value={summary} maxLength={2000} rows={5} onChange={event => setSummary(event.target.value)}/>
    <label htmlFor="scenario-valid-from">现实开始时间（可选）</label><Input id="scenario-valid-from" type="datetime-local" value={validFrom} onChange={event => setValidFrom(event.target.value)}/>
    <label htmlFor="scenario-valid-to">现实结束时间（可选）</label><Input id="scenario-valid-to" type="datetime-local" value={validTo} onChange={event => setValidTo(event.target.value)}/>
    {validFrom && validTo && new Date(validTo) < new Date(validFrom) && <Alert type="error" showIcon title="结束时间不能早于开始时间"/>}
    <label htmlFor="scenario-sources">L1 来源（至少两条）</label><Select id="scenario-sources" aria-label="L1 来源" mode="multiple" className="wide" value={sourceIds} onChange={setSourceIds}
      optionFilterProp="label" options={sourceOptions}/>
    <Checkbox checked={inboxOnly} onChange={event => setInboxOnly(event.target.checked)}>
      只显示待整理 L1（{sourceInbox.data?.total ?? 0}）
    </Checkbox>
    <Alert type="info" showIcon title="待整理只表示尚未被当前 L2 覆盖"
      description="系统没有判断这些记忆属于同一个主题。仍需由你选择真正相关的至少两条来源；不会自动调用模型或写入场景。"/>
    <Space direction="vertical" className="wide">
      <Button block loading={previewCandidate.isPending}
        disabled={!config.data?.scenario_model_preview_available || sourceIds.length < 2}
        onClick={() => {setPreviewMode('selected'); setConfirmingModel(true);}}>用学校模型生成草稿</Button>
      {!config.data?.scenario_model_preview_available && <small>当前启动方式没有可用的 L2 模型预览；仍可人工填写。</small>}
      {draftOrigin === 'model_assisted' && <Alert type="warning" showIcon title="当前内容来自模型辅助草稿"
        description="尚未写库。请核对标题、总结和来源；你可以直接修改，创建后仍是待复核候选。"/>}
    </Space>
  </Modal></>;
}
