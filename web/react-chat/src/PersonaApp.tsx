import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, Drawer, Empty, Input, List, Modal, Select, Space, Tag} from 'antd';
import {ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';

type PersonaState = 'candidate' | 'active' | 'rejected' | 'stale';
type PersonaKind = 'preference' | 'habit' | 'interaction_style' | 'behavior_pattern';
type PersonaBasis = 'user_declared' | 'system_inferred';
type MemoryConfig = {configured:boolean;database:string|null;allow_persona_management:boolean;
  persona_model_preview_available:boolean;persona_model:string|null};
type Persona = {id:string;subject_id:string;kind:PersonaKind;basis:PersonaBasis;label:string;statement:string;
  generated_at:string;valid_from:string|null;valid_to:string|null;status:PersonaState;generator_name:string;generator_version:string;revision:number};
type PersonaSource = {source_layer:'l1'|'l2';source_id:string;source_content_snapshot:string;linked_at:string;
  current_content:string|null;active:boolean;l0_sources:Array<{id:string;content:string;created_at:string;source_type:string}>};
type PersonaDetail = Persona & {audit:{source_count:number;source_message_count:number;observation_day_count:number}|null;
  sources:PersonaSource[];lifecycle_events:Array<{id:string;action:string;source_layer:string;source_id:string;occurred_at:string;persona_revision:number}>};
type SourceOption = {layer:'l1'|'l2';id:string;subject_id:string;content:string;recorded_at:string};
type SourceOptions = {l1:SourceOption[];l2:SourceOption[];selection_is_semantic:false};
type PersonaProposal = {kind:PersonaKind;basis:PersonaBasis;label:string;statement:string;
  sources:Array<{layer:'l1'|'l2';id:string}>;generator_name:string;generator_version:string;model:string|null;persisted:false};
type Page<T> = {items:T[];total:number;limit:number;offset:number};

const api = new ChatApi();
const stateName:Record<PersonaState,string> = {candidate:'待复核',active:'已接受',rejected:'已拒绝',stale:'已失效'};
const stateColor:Record<PersonaState,string> = {candidate:'gold',active:'green',rejected:'default',stale:'red'};
const kindName:Record<PersonaKind,string> = {preference:'偏好',habit:'习惯',interaction_style:'互动方式',behavior_pattern:'行为模式'};
const basisName:Record<PersonaBasis,string> = {user_declared:'用户明确声明',system_inferred:'系统跨记录推断'};
const displayTime = (value?:string|null) => value ? new Date(value).toLocaleString('zh-CN') : '未记录';
const sourceKey = (item:{layer:'l1'|'l2';id:string}) => JSON.stringify([item.layer,item.id]);
const parseSource = (value:string) => {const [layer,id] = JSON.parse(value) as ['l1'|'l2',string]; return {layer,id};};

/** L3 先保存可核对候选；助手角色、单次印象和未复核推断都不能成为用户画像。 */
export function PersonaApp() {
  const queryClient = useQueryClient();
  const [ready,setReady] = useState(false);
  const [notice,setNotice] = useState('正在连接本机记忆服务…');
  const [filter,setFilter] = useState<'all'|PersonaState>('all');
  const [selectedId,setSelectedId] = useState<string>();
  const [creating,setCreating] = useState(false);
  const [confirmingModel,setConfirmingModel] = useState(false);
  const [draftOrigin,setDraftOrigin] = useState<'manual'|'model_assisted'>('manual');
  const [reviewDecision,setReviewDecision] = useState<'accepted'|'rejected'>();
  const [kind,setKind] = useState<PersonaKind>('preference');
  const [basis,setBasis] = useState<PersonaBasis>('user_declared');
  const [label,setLabel] = useState('');
  const [statement,setStatement] = useState('');
  const [sources,setSources] = useState<string[]>([]);
  const [validFrom,setValidFrom] = useState('');
  const [validTo,setValidTo] = useState('');

  useEffect(() => {void api.bootstrap().then(() => setReady(true)).catch(error => setNotice(String(error)));},[]);
  const config = useQuery({queryKey:['memory-config'],enabled:ready,queryFn:() => api.request<MemoryConfig>('/api/memory-config')});
  const personas = useQuery({queryKey:['personas',filter],enabled:ready&&config.data?.configured===true,
    queryFn:() => api.request<Page<Persona>>(`/api/personas?state=${filter}&offset=0&limit=100`)});
  const sourceOptions = useQuery({queryKey:['persona-source-options'],enabled:ready&&config.data?.configured===true,
    queryFn:() => api.request<SourceOptions>('/api/persona-source-options')});
  const detail = useQuery({queryKey:['persona',selectedId],enabled:ready&&Boolean(selectedId),
    queryFn:() => api.request<PersonaDetail>(`/api/personas/${encodeURIComponent(selectedId!)}`)});

  const createCandidate = useMutation({
    mutationFn:() => api.request<{id:string}>('/api/personas','POST',{
      kind,basis,label:label.trim(),statement:statement.trim(),sources:sources.map(parseSource),
      valid_from:validFrom?new Date(validFrom).toISOString():null,
      valid_to:validTo?new Date(validTo).toISOString():null,
      creation_kind:draftOrigin,confirm_candidate:true,
    }),
    onSuccess:async result => {setCreating(false);setSelectedId(result.id);setLabel('');setStatement('');setSources([]);setValidFrom('');setValidTo('');
      await queryClient.invalidateQueries({queryKey:['personas']});setNotice('L3 画像候选已创建，尚未成为有效画像。');},
    onError:error => setNotice(String(error)),
  });
  const previewCandidate = useMutation({
    mutationFn:() => api.request<PersonaProposal>('/api/persona-proposals','POST',{
      basis,sources:sources.map(parseSource),confirm_model_call:true,
    }),
    onSuccess:proposal => {
      setConfirmingModel(false);setKind(proposal.kind);setBasis(proposal.basis);
      setLabel(proposal.label);setStatement(proposal.statement);
      setSources(proposal.sources.map(sourceKey));setDraftOrigin('model_assisted');
      setNotice(`模型草稿已返回（${proposal.model??'未标记模型'}），尚未写入数据库；请核对 L0 原话、修改草稿后再创建候选。`);
    },
    onError:error => {setConfirmingModel(false);setNotice(String(error));},
  });
  const review = useMutation({
    mutationFn:(decision:'accepted'|'rejected') => api.request(`/api/personas/${encodeURIComponent(selectedId!)}/reviews`,'POST',{
      decision,expected_revision:detail.data!.revision,confirm_review:true,
    }),
    onSuccess:async() => {setReviewDecision(undefined);await Promise.all([
      queryClient.invalidateQueries({queryKey:['personas']}),queryClient.invalidateQueries({queryKey:['persona',selectedId]}),
    ]);setNotice('画像复核结果已保存；当前版本仍不会把 L3 注入聊天回答。');},
    onError:error => setNotice(String(error)),
  });
  const canManage = config.data?.allow_persona_management===true;
  const options = [...(sourceOptions.data?.l1??[]),...(sourceOptions.data?.l2??[])].map(item => ({
    value:sourceKey(item),label:`${item.layer.toUpperCase()} · ${item.content}`,
  }));
  const validRange = !(validFrom&&validTo&&new Date(validTo)<new Date(validFrom));
  const openCreator = () => {setKind('preference');setBasis('user_declared');setLabel('');setStatement('');setSources([]);setValidFrom('');setValidTo('');setDraftOrigin('manual');setCreating(true);};
  const sidebar = <><Button type="primary" block disabled={!canManage} onClick={openCreator}>新建 L3 候选</Button><ConsoleNav active="personas" legacyPath="/memories"/></>;

  return <><AppShell subtitle="可复核的用户画像" className="persona-shell" sidebar={sidebar}>
    <header><div><h1>用户画像（L3）</h1><small>{config.data?.database??'未指定记忆库'}</small></div>
      <Button loading={personas.isFetching} onClick={() => void queryClient.invalidateQueries({queryKey:['personas']})}>刷新</Button></header>
    <Alert className="mode-card" type="info" showIcon title="L3 是关于用户的稳定认识，不是助手角色"
      description="用户声明与系统推断分开标记；所有内容先成为候选并检查 L1/L2→L0 来源。当前版本尚不把 L3 用于回答。"/>
    {!canManage&&config.data?.configured&&<Alert type="warning" showIcon title="当前进程没有开启 L3 管理权限" description="通过新版日常启动面板启动可开放候选与复核；只读浏览不受影响。"/>}
    <div className="scenario-toolbar"><Select aria-label="画像状态" value={filter} onChange={setFilter} options={[
      {value:'all',label:'全部状态'},{value:'candidate',label:'待复核'},{value:'active',label:'已接受'},
      {value:'rejected',label:'已拒绝'},{value:'stale',label:'已失效'},
    ]}/></div>
    <List loading={personas.isFetching} dataSource={personas.data?.items??[]} locale={{emptyText:<Empty description="尚无 L3 用户画像"/>}}
      renderItem={item=><List.Item className="memory-item" onClick={() => setSelectedId(item.id)} actions={[<Button key="open" type="link">查看证据</Button>]}>
        <List.Item.Meta title={<Space wrap><span>{item.label}</span><Tag>{kindName[item.kind]}</Tag><Tag color={item.basis==='user_declared'?'blue':'purple'}>{basisName[item.basis]}</Tag><Tag color={stateColor[item.status]}>{stateName[item.status]}</Tag></Space>}
          description={<><p className="scenario-summary">{item.statement}</p><small>{displayTime(item.generated_at)} · 修订 {item.revision}</small></>}/></List.Item>}/>
    <p role="status">{config.error?String(config.error):personas.error?String(personas.error):notice}</p>
  </AppShell>

  <Drawer title="L3 画像详情" size="large" open={Boolean(selectedId)} onClose={() => setSelectedId(undefined)} loading={detail.isFetching}>
    {detail.data&&<><Space wrap><h2>{detail.data.label}</h2><Tag>{kindName[detail.data.kind]}</Tag><Tag color={detail.data.basis==='user_declared'?'blue':'purple'}>{basisName[detail.data.basis]}</Tag><Tag color={stateColor[detail.data.status]}>{stateName[detail.data.status]}</Tag></Space>
      <p className="detail-content">{detail.data.statement}</p>
      <Descriptions column={1} size="small" bordered items={[
        {key:'subject',label:'主体',children:detail.data.subject_id},{key:'generated',label:'生成时间',children:displayTime(detail.data.generated_at)},
        {key:'validFrom',label:'现实开始时间',children:displayTime(detail.data.valid_from)},{key:'validTo',label:'现实结束时间',children:displayTime(detail.data.valid_to)},
        {key:'sourceCount',label:'证据覆盖',children:detail.data.audit?`${detail.data.audit.source_count} 个来源 · ${detail.data.audit.source_message_count} 条用户原话 · ${detail.data.audit.observation_day_count} 个观察日`:'审计缺失'},
        {key:'revision',label:'修订号',children:String(detail.data.revision)},
      ]}/>
      <h3>L1/L2 来源与 L0 原话</h3>{detail.data.sources.map(source=><Card className="source-card" key={`${source.source_layer}:${source.source_id}`} size="small" title={`${source.source_layer.toUpperCase()} · ${source.source_id}`} extra={<Tag color={source.active?'green':'red'}>{source.active?'仍有效':'已失效'}</Tag>}>
        <p>{source.source_content_snapshot}</p>{source.current_content!==source.source_content_snapshot&&<p className="memory-warning">当前内容与创建时快照不同：{source.current_content??'来源已不存在或失效'}</p>}
        <details><summary>查看用户 L0 原话（{source.l0_sources.length}）</summary>{source.l0_sources.map(item=><blockquote key={item.id}><p>{item.content}</p><small>{item.source_type} · {displayTime(item.created_at)}</small></blockquote>)}</details>
      </Card>)}
      {detail.data.status==='candidate'&&<Space><Button type="primary" disabled={!canManage} onClick={() => setReviewDecision('accepted')}>接受</Button><Button danger disabled={!canManage} onClick={() => setReviewDecision('rejected')}>拒绝</Button></Space>}
      <h3>来源失效记录</h3>{detail.data.lifecycle_events.length?<List size="small" dataSource={detail.data.lifecycle_events} renderItem={event=><List.Item>{event.source_layer.toUpperCase()} {event.source_id} · {event.action} · {displayTime(event.occurred_at)}</List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无来源失效事件"/>}
    </>}
  </Drawer>

  <Modal title="新建 L3 用户画像候选" open={creating} okText="创建待复核候选" cancelText="取消" confirmLoading={createCandidate.isPending}
    okButtonProps={{disabled:!label.trim()||!statement.trim()||sources.length<1||!validRange}} onCancel={() => setCreating(false)} onOk={() => createCandidate.mutate()}>
    <Alert type={basis==='system_inferred'?'warning':'info'} showIcon title={basis==='system_inferred'?'系统推断需要跨记录证据':'用户声明必须能回到用户原话'}
      description={basis==='system_inferred'?'服务端强制要求至少 2 个来源、3 条不同用户 L0、2 个观察日；达到门槛也不等于推断必然正确。':'至少选择一个能直接支持这条声明的 L1 或已接受 L2，创建后仍需复核。'}/>
    <label htmlFor="persona-kind">画像类型</label><Select id="persona-kind" className="wide" value={kind} onChange={setKind} options={Object.entries(kindName).map(([value,label])=>({value,label}))}/>
    <label htmlFor="persona-basis">依据性质</label><Select id="persona-basis" className="wide" value={basis} onChange={value=>{setBasis(value);setDraftOrigin('manual');}} options={Object.entries(basisName).map(([value,label])=>({value,label}))}/>
    <label htmlFor="persona-label">简短标签</label><Input id="persona-label" value={label} maxLength={120} onChange={event=>setLabel(event.target.value)} placeholder="例如：建议前先倾听"/>
    <label htmlFor="persona-statement">画像断言</label><Input.TextArea id="persona-statement" value={statement} maxLength={1000} rows={4} onChange={event=>setStatement(event.target.value)} placeholder="一次只写一条可独立核对的认识"/>
    <label htmlFor="persona-sources">证据来源</label><Select id="persona-sources" aria-label="画像证据来源" mode="multiple" className="wide" value={sources} onChange={setSources} optionFilterProp="label" options={options}/>
    <Space direction="vertical" className="wide">
      <Button disabled={!config.data?.persona_model_preview_available||sources.length<1} onClick={()=>setConfirmingModel(true)}>让模型生成不落库草稿</Button>
      <small>{config.data?.persona_model_preview_available
        ? `调用前会再次确认；当前模型：${config.data.persona_model??'未标记'}`
        : '当前启动方式没有可用的 L3 草稿模型，仍可手工填写。'}</small>
      {draftOrigin==='model_assisted'&&<Tag color="purple">当前内容来自模型草稿，已允许人工修改</Tag>}
    </Space>
    <label htmlFor="persona-valid-from">现实开始时间（可选）</label><Input id="persona-valid-from" type="datetime-local" value={validFrom} onChange={event=>setValidFrom(event.target.value)}/>
    <label htmlFor="persona-valid-to">现实结束时间（可选）</label><Input id="persona-valid-to" type="datetime-local" value={validTo} onChange={event=>setValidTo(event.target.value)}/>
    {!validRange&&<Alert type="error" showIcon title="结束时间不能早于开始时间"/>}
  </Modal>

  <Modal title="确认发送所选记忆给模型" open={confirmingModel} centered width={620} zIndex={1400}
    confirmLoading={previewCandidate.isPending} okText="生成不落库草稿" cancelText="取消"
    onCancel={()=>!previewCandidate.isPending&&setConfirmingModel(false)}
    onOk={()=>previewCandidate.mutate()}>
    <p>将发送 {sources.length} 个已选 L1/L2 的内容，以及它们向下追溯到的用户 L0 原话和 UTC 观察日期。</p>
    <p>模型只返回可编辑草稿，不会自动创建、接受或用于回答；调用失败不会重试。</p>
    <Alert type="warning" showIcon title="个人记忆将发送给当前配置的模型服务" description="只选择支持本画像的必要来源。来源中的文本按不可信数据处理，不能指挥模型或管理接口。"/>
  </Modal>

  <Modal title={reviewDecision==='accepted'?'确认接受 L3 画像':'确认拒绝 L3 候选'} open={Boolean(reviewDecision)} centered width={580} zIndex={1300}
    okText={reviewDecision==='accepted'?'确认接受':'确认拒绝'} cancelText="返回核对" confirmLoading={review.isPending}
    okButtonProps={{danger:reviewDecision==='rejected'}} onCancel={() => !review.isPending&&setReviewDecision(undefined)} onOk={() => reviewDecision&&review.mutate(reviewDecision)}>
    <p><strong>{detail.data?.label}</strong></p><p>{detail.data?.statement}</p>
    <p>{reviewDecision==='accepted'?'接受后成为有效画像，但当前切片仍不会自动参与回答。':'拒绝后保留候选和证据用于审计，不会物理删除。'}</p>
    <p>请确认已经核对 L1/L2 内容、底层 L0 原话和“用户声明/系统推断”标记。</p>
  </Modal></>;
}
