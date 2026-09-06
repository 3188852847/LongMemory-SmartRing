import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, Drawer, Empty, Input, List, Modal, Select, Space, Tag} from 'antd';
import {ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';

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
type ScenarioDetail = Scenario & {sources: ScenarioSource[]};
type Page<T> = {items: T[]; total: number; limit: number; offset: number};
type ScenarioProposal = {title: string; summary: string; source_memory_ids: string[];
  generator_name: string; generator_version: string; model: string | null; persisted: false};

const api = new ChatApi();
const stateName: Record<ScenarioState, string> = {candidate: '待复核', active: '已接受', rejected: '已拒绝', stale: '来源已变化'};
const stateColor: Record<ScenarioState, string> = {candidate: 'gold', active: 'green', rejected: 'default', stale: 'red'};
const displayTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未记录';

/** L2 是多条 L1 汇总出的生活场景；页面只管理候选，不改变聊天注入策略。 */
export function ScenarioApp() {
  const queryClient = useQueryClient();
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState('正在连接本机记忆服务…');
  const [filter, setFilter] = useState<'all' | ScenarioState>('all');
  const [selectedId, setSelectedId] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [draftOrigin, setDraftOrigin] = useState<'manual' | 'model_assisted'>('manual');
  const [confirmingModel, setConfirmingModel] = useState(false);
  const [reviewDecision, setReviewDecision] = useState<'accepted' | 'rejected'>();

  useEffect(() => {void api.bootstrap().then(() => setReady(true)).catch(error => setNotice(String(error)));}, []);
  const config = useQuery({queryKey: ['memory-config'], enabled: ready,
    queryFn: () => api.request<MemoryConfig>('/api/memory-config')});
  const scenarios = useQuery({queryKey: ['scenarios', filter], enabled: ready && config.data?.configured === true,
    queryFn: () => api.request<Page<Scenario>>(`/api/scenarios?state=${filter}&offset=0&limit=100`)});
  const memories = useQuery({queryKey: ['scenario-source-l1'], enabled: ready && config.data?.configured === true,
    queryFn: () => api.request<Page<L1>>('/api/memories?state=active&q=&offset=0&limit=100')});
  const detail = useQuery({queryKey: ['scenario', selectedId], enabled: ready && Boolean(selectedId),
    queryFn: () => api.request<ScenarioDetail>(`/api/scenarios/${encodeURIComponent(selectedId!)}`)});

  const createCandidate = useMutation({
    mutationFn: () => api.request<{id: string}>('/api/scenarios', 'POST', {
      title: title.trim(), summary: summary.trim(), source_memory_ids: sourceIds,
      creation_kind: draftOrigin, confirm_candidate: true,
    }),
    onSuccess: async result => {
      setCreating(false); setTitle(''); setSummary(''); setSourceIds([]); setDraftOrigin('manual'); setSelectedId(result.id);
      await queryClient.invalidateQueries({queryKey: ['scenarios']});
      setNotice('L2 候选已创建，尚未进入已接受状态。');
    },
    onError: error => setNotice(String(error)),
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
    onError: error => {setConfirmingModel(false); setNotice(String(error));},
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
      setNotice('复核结果已保存；本阶段仍不会把 L2 自动注入回答。');
    },
    onError: error => setNotice(String(error)),
  });
  const busy = config.isFetching || scenarios.isFetching || memories.isFetching || detail.isFetching || createCandidate.isPending || previewCandidate.isPending || review.isPending;
  const canManage = config.data?.allow_scenario_management === true;
  const openCreator = () => {setTitle(''); setSummary(''); setSourceIds([]); setDraftOrigin('manual'); setCreating(true);};
  const sidebar = <><Button type="primary" block disabled={!canManage} onClick={openCreator}>新建 L2 候选</Button>
    <ConsoleNav active="scenarios" legacyPath="/memories"/></>;

  return <><AppShell subtitle="可复核的生活场景" className="scenario-shell" sidebar={sidebar}>
    <header><div><h1>生活场景（L2）</h1><small>{config.data?.database ?? '未指定记忆库'}</small></div>
      <Button loading={busy} onClick={() => void queryClient.invalidateQueries({queryKey: ['scenarios']})}>刷新</Button></header>
    <Alert className="mode-card" type="info" showIcon title="当前是可复核 L2 候选阶段"
      description="L2 把多条 L1 原子记忆汇总成生活场景。可以人工填写，也可以把明确选中的 L1 交给模型生成不落库草稿；创建、接受后仍不参与聊天检索或回答。"/>
    {!canManage && config.data?.configured && <Alert type="warning" showIcon title="当前进程没有开启 L2 管理权限" description="通过日常启动面板启动时会开启；只读浏览仍可使用。"/>}
    <div className="scenario-toolbar"><Select aria-label="场景状态" value={filter} onChange={value => setFilter(value)} options={[
      {value:'all',label:'全部状态'}, {value:'candidate',label:'待复核'}, {value:'active',label:'已接受'},
      {value:'rejected',label:'已拒绝'}, {value:'stale',label:'来源已变化'},
    ]}/></div>
    <List loading={scenarios.isFetching} dataSource={scenarios.data?.items ?? []} locale={{emptyText:<Empty description="尚无 L2 生活场景"/>}}
      renderItem={item => <List.Item className="memory-item" onClick={() => setSelectedId(item.id)} actions={[<Button key="open" type="link">查看来源</Button>]}
        ><List.Item.Meta title={<Space wrap><span>{item.title}</span><Tag color={stateColor[item.status]}>{stateName[item.status]}</Tag></Space>}
          description={<><p className="scenario-summary">{item.summary}</p><small>{displayTime(item.generated_at)} · 修订 {item.revision}</small></>}/></List.Item>}/>
    <p role="status">{config.error ? String(config.error) : scenarios.error ? String(scenarios.error) : notice}</p>
  </AppShell>

  <Drawer title="L2 场景详情" size="large" open={Boolean(selectedId)} onClose={() => setSelectedId(undefined)} loading={detail.isFetching}>
    {detail.data && <><Space wrap><h2>{detail.data.title}</h2><Tag color={stateColor[detail.data.status]}>{stateName[detail.data.status]}</Tag></Space>
      <p className="detail-content">{detail.data.summary}</p>
      <Descriptions column={1} size="small" bordered items={[
        {key:'subject',label:'主体',children:detail.data.subject_id}, {key:'generated',label:'生成时间',children:displayTime(detail.data.generated_at)},
        {key:'generator',label:'生成方式',children:`${detail.data.generator_name} ${detail.data.generator_version}`},
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
    </>}
  </Drawer>

  <Modal title={reviewDecision === 'accepted' ? '确认接受 L2 场景' : '确认拒绝 L2 候选'}
    open={Boolean(reviewDecision)} centered width={560} zIndex={1300}
    confirmLoading={review.isPending} okText={reviewDecision === 'accepted' ? '确认接受' : '确认拒绝'} cancelText="返回核对"
    okButtonProps={{danger: reviewDecision === 'rejected'}} onCancel={() => !review.isPending && setReviewDecision(undefined)}
    onOk={() => reviewDecision && review.mutateAsync(reviewDecision)}>
    <p><strong>{detail.data?.title ?? '当前场景'}</strong></p>
    <p>{reviewDecision === 'accepted'
      ? '接受只改变复核状态，当前不会把这条 L2 自动注入网页或圆屏回答。'
      : '拒绝后候选会保留用于来源审计，不会物理删除。'}</p>
    <p>请确认已经核对上方详情中的 L1 内容与 L0 原话。</p>
  </Modal>

  <Modal title="确认发送所选 L1 给学校模型" open={confirmingModel} centered width={600} zIndex={1300}
    confirmLoading={previewCandidate.isPending} okText="生成不落库草稿" cancelText="取消"
    onCancel={() => !previewCandidate.isPending && setConfirmingModel(false)}
    onOk={() => previewCandidate.mutate()}>
    <p>本次会把你明确选择的 {sourceIds.length} 条 L1 记忆发送给当前学校模型，用于生成一个 L2 草稿。</p>
    <p>模型只调用一次，不自动重试；返回内容不会自动写入数据库，也不会进入聊天回答。</p>
    <p>当前模型：{config.data?.scenario_model ?? '未标记'}</p>
  </Modal>

  <Modal title="新建 L2 候选" open={creating} confirmLoading={createCandidate.isPending} okText="创建待复核候选" cancelText="取消"
    okButtonProps={{disabled: !title.trim() || !summary.trim() || sourceIds.length < 2}}
    onCancel={() => setCreating(false)} onOk={() => createCandidate.mutate()}>
    <p>至少选择两条同一主体、来源可追溯的活跃 L1。模型只能生成草稿，不会自动保存或接受。</p>
    <label htmlFor="scenario-title">场景标题</label><Input id="scenario-title" value={title} maxLength={120} onChange={event => setTitle(event.target.value)}/>
    <label htmlFor="scenario-summary">场景总结</label><Input.TextArea id="scenario-summary" value={summary} maxLength={2000} rows={5} onChange={event => setSummary(event.target.value)}/>
    <label htmlFor="scenario-sources">L1 来源（至少两条）</label><Select id="scenario-sources" aria-label="L1 来源" mode="multiple" className="wide" value={sourceIds} onChange={setSourceIds}
      optionFilterProp="label" options={(memories.data?.items ?? []).map(item => ({value:item.id,label:item.content}))}/>
    <Space direction="vertical" className="wide">
      <Button block loading={previewCandidate.isPending}
        disabled={!config.data?.scenario_model_preview_available || sourceIds.length < 2}
        onClick={() => setConfirmingModel(true)}>用学校模型生成草稿</Button>
      {!config.data?.scenario_model_preview_available && <small>当前启动方式没有可用的 L2 模型预览；仍可人工填写。</small>}
      {draftOrigin === 'model_assisted' && <Alert type="warning" showIcon title="当前内容来自模型辅助草稿"
        description="尚未写库。请核对标题、总结和来源；你可以直接修改，创建后仍是待复核候选。"/>}
    </Space>
  </Modal></>;
}
