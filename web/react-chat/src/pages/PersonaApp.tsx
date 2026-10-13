import {DataWorkspace, useWorkspaceParam} from '../features/data-workspace/DataWorkspace';
import {useUnsavedChanges} from '../app/UnsavedChanges';
import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, Drawer, Empty, Input, List, Modal, Select, Space, Tag} from 'antd';
import {ChatApi} from '../api';
import {AppShell, ConsoleNav} from '../components/AppShell';
import {PageHeader} from '../components/PageHeader';
import {ConsolidationStatusCard} from '../features/memory/ConsolidationStatusCard';
import {derivedMemoryFailure} from '../features/memory/derivedMemoryFailure';

type PersonaState = 'candidate' | 'active' | 'rejected' | 'stale';
type PersonaKind = 'preference' | 'habit' | 'interaction_style' | 'behavior_pattern';
type PersonaBasis = 'user_declared' | 'system_inferred';
type MemoryConfig = {configured:boolean;database:string|null;allow_persona_management:boolean;
  persona_model_preview_available:boolean;persona_model:string|null};
type Persona = {id:string;subject_id:string;kind:PersonaKind;basis:PersonaBasis;label:string;statement:string;
  generated_at:string;valid_from:string|null;valid_to:string|null;status:PersonaState;generator_name:string;generator_version:string;revision:number};
type PersonaSource = {source_layer:'l1'|'l2';source_id:string;source_content_snapshot:string;linked_at:string;
  current_content:string|null;active:boolean;l0_sources:Array<{id:string;content:string;created_at:string;source_type:string}>};
type PersonaReplacement = {candidate_persona_id:string;replaced_persona_id:string;target_revision:number;
  linked_at:string;applied_at:string|null;related:Persona|null};
type PersonaDetail = Persona & {audit:{source_count:number;source_message_count:number;observation_day_count:number}|null;
  sources:PersonaSource[];replaces?:PersonaReplacement[];replaced_by?:PersonaReplacement[];
  review?:{decision:'accepted'|'rejected';reviewer_type:'user'|'policy';reviewed_at:string;
    persona_revision:number;policy_version:string|null;decision_reason:string|null}|null;
  lifecycle_events:Array<{id:string;action:string;source_layer:string;source_id:string;occurred_at:string;persona_revision:number}>};
type SourceOption = {layer:'l1'|'l2';id:string;subject_id:string;content:string;recorded_at:string};
type SourceOptions = {l1:SourceOption[];l2:SourceOption[];selection_is_semantic:false};
type PersonaProposal = {kind:PersonaKind;basis:PersonaBasis;label:string;statement:string;
  sources:Array<{layer:'l1'|'l2';id:string}>;generator_name:string;generator_version:string;model:string|null;persisted:false};
type PersonaConsolidationProposal = {operation:'ADD'|'UPDATE'|'NOOP';candidate:PersonaProposal|null;
  replaces:string[];generator_name:string;generator_version:string;model:string|null;persisted:false};
type PersonaProfile = {subject_id:string;representation:'aggregated_active_assertions_v1';updated_at:string|null;
  active_assertion_count:number;status_counts:Record<PersonaState,number>;
  sections:Array<{kind:PersonaKind;items:Persona[]}>};
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
  const [workspace,setWorkspace] = useWorkspaceParam('view','profile',['profile','evidence','consolidation']);
  const [filterValue,setFilter] = useWorkspaceParam('state','all',['all','candidate','active','rejected','stale']);
  const filter = filterValue as 'all'|PersonaState;
  const [query,setQuery] = useWorkspaceParam('q','');
  const [selectedValue,selectId] = useWorkspaceParam('persona_id','');
  const selectedId = selectedValue.length<=128 ? selectedValue || undefined : undefined;
  const setSelectedId = (value:string|undefined) => selectId(value??'');
  const [creating,setCreating] = useState(false);
  const [confirmingModel,setConfirmingModel] = useState(false);
  const [draftOrigin,setDraftOrigin] = useState<'manual'|'model_assisted'|'model_consolidation'>('manual');
  const [reviewDecision,setReviewDecision] = useState<'accepted'|'rejected'>();
  const [kind,setKind] = useState<PersonaKind>('preference');
  const [basis,setBasis] = useState<PersonaBasis>('user_declared');
  const [label,setLabel] = useState('');
  const [statement,setStatement] = useState('');
  const [sources,setSources] = useState<string[]>([]);
  const [validFrom,setValidFrom] = useState('');
  const [validTo,setValidTo] = useState('');
  const [replacementIds,setReplacementIds] = useState<string[]>([]);
  useUnsavedChanges(creating && Boolean(label || statement || sources.length || validFrom || validTo || replacementIds.length), '有未保存的画像候选。');

  useEffect(() => {void api.bootstrap().then(() => setReady(true)).catch(error => setNotice(derivedMemoryFailure(error, 'read')));},[]);
  const config = useQuery({queryKey:['memory-config'],enabled:ready,queryFn:() => api.request<MemoryConfig>('/api/memory-config')});
  const personas = useQuery({queryKey:['personas',filter],enabled:ready&&config.data?.configured===true,
    queryFn:() => api.request<Page<Persona>>(`/api/personas?state=${filter}&offset=0&limit=100`)});
  const profile = useQuery({queryKey:['persona-profile'],enabled:ready&&config.data?.configured===true,
    queryFn:() => api.request<PersonaProfile>('/api/persona-profile')});
  const sourceOptions = useQuery({queryKey:['persona-source-options'],enabled:ready&&config.data?.configured===true,
    queryFn:() => api.request<SourceOptions>('/api/persona-source-options')});
  const detail = useQuery({queryKey:['persona',selectedId],enabled:ready&&Boolean(selectedId),
    queryFn:() => api.request<PersonaDetail>(`/api/personas/${encodeURIComponent(selectedId!)}`)});
  const closeDetail = () => setSelectedId(undefined);

  const createCandidate = useMutation({
    mutationFn:() => api.request<{id:string}>('/api/personas','POST',{
      kind,basis,label:label.trim(),statement:statement.trim(),sources:sources.map(parseSource),
      valid_from:validFrom?new Date(validFrom).toISOString():null,
      valid_to:validTo?new Date(validTo).toISOString():null,
      creation_kind:draftOrigin,replaces:replacementIds,confirm_candidate:true,
    }),
    onSuccess:async result => {setCreating(false);setSelectedId(result.id);setLabel('');setStatement('');setSources([]);setValidFrom('');setValidTo('');setReplacementIds([]);
      await queryClient.invalidateQueries({queryKey:['personas']});setNotice('L3 画像候选已创建，尚未成为有效画像。');},
    onError:error => setNotice(derivedMemoryFailure(error, 'write')),
  });
  const previewCandidate = useMutation({
    mutationFn:() => api.request<PersonaConsolidationProposal>('/api/persona-consolidation-proposals','POST',{
      basis,sources:sources.map(parseSource),confirm_model_call:true,
    }),
    onSuccess:proposal => {
      setConfirmingModel(false);
      if(proposal.operation==='NOOP'||!proposal.candidate){
        setNotice(`整理器建议 NOOP（${proposal.model??'未标记模型'}）：现有证据不足以新增或更新画像，没有写入数据库。`);
        return;
      }
      setKind(proposal.candidate.kind);setBasis(proposal.candidate.basis);
      setLabel(proposal.candidate.label);setStatement(proposal.candidate.statement);
      setSources(proposal.candidate.sources.map(sourceKey));setReplacementIds(proposal.replaces);
      setDraftOrigin('model_consolidation');
      setNotice(`整理器建议 ${proposal.operation}（${proposal.model??'未标记模型'}），尚未写入数据库；请核对、编辑后再创建候选。`);
    },
    onError:error => {setConfirmingModel(false);setNotice(derivedMemoryFailure(error, 'preview'));},
  });
  const review = useMutation({
    mutationFn:(decision:'accepted'|'rejected') => api.request(`/api/personas/${encodeURIComponent(selectedId!)}/reviews`,'POST',{
      decision,expected_revision:detail.data!.revision,confirm_review:true,
    }),
    onSuccess:async() => {setReviewDecision(undefined);await Promise.all([
      queryClient.invalidateQueries({queryKey:['personas']}),queryClient.invalidateQueries({queryKey:['persona',selectedId]}),
      queryClient.invalidateQueries({queryKey:['persona-profile']}),
    ]);setNotice('画像复核结果已保存；当前版本仍不会把 L3 注入聊天回答。');},
    onError:error => setNotice(derivedMemoryFailure(error, 'write')),
  });
  const canManage = config.data?.allow_persona_management===true;
  const options = [...(sourceOptions.data?.l1??[]),...(sourceOptions.data?.l2??[])].map(item => ({
    value:sourceKey(item),label:`${item.layer.toUpperCase()} · ${item.content}`,
  }));
  const validRange = !(validFrom&&validTo&&new Date(validTo)<new Date(validFrom));
  const openCreator = () => {setKind('preference');setBasis('user_declared');setLabel('');setStatement('');setSources([]);setValidFrom('');setValidTo('');setReplacementIds([]);setDraftOrigin('manual');setCreating(true);};
  const openReplacement = () => {
    if(!detail.data) return;
    setKind(detail.data.kind);setBasis(detail.data.basis);setLabel(detail.data.label);setStatement(detail.data.statement);
    setSources(detail.data.sources.filter(source=>source.active).map(source=>sourceKey({layer:source.source_layer,id:source.source_id})));
    // 现实时间由用户重新确认，不能把旧值或 UTC 字符串静默冒充本地输入。
    setValidFrom('');setValidTo('');
    setReplacementIds([detail.data.id]);setDraftOrigin('manual');setCreating(true);
  };
  const sidebar = <><Button type="primary" block disabled={!canManage} onClick={openCreator}>新建 L3 候选</Button><ConsoleNav active="personas" legacyPath="/memories"/></>;
  const profilePane = <Card title="我的统一画像" extra={<Space><Tag color="green">{profile.data?.active_assertion_count??0} 项已接受认识</Tag><small>更新：{displayTime(profile.data?.updated_at)}</small></Space>}>
    {profile.isFetching?<p>正在整理当前画像…</p>:profile.data?.sections.length?<Space orientation="vertical" size="middle" className="wide">
      {profile.data.sections.map(section=><Card key={section.kind} type="inner" title={kindName[section.kind]}>
        <List dataSource={section.items} renderItem={item=><List.Item actions={[<Button key="evidence" type="link" onClick={()=>setSelectedId(item.id)}>查看依据</Button>]}>
          <List.Item.Meta title={<Space wrap><span>{item.label}</span><Tag color={item.basis==='user_declared'?'blue':'purple'}>{basisName[item.basis]}</Tag></Space>}
            description={<><p className="scenario-summary">{item.statement}</p>{(item.valid_from||item.valid_to)&&<small>现实时间：{displayTime(item.valid_from)} — {displayTime(item.valid_to)}</small>}</>}/>
        </List.Item>}/>
      </Card>)}
    </Space>:<Empty description="尚无已接受的画像认识；候选需在“画像依据与候选”中复核后才会进入这里"/>}
  </Card>;
  const evidencePane = <>
    <div className="scenario-toolbar"><Input aria-label="搜索已加载画像" allowClear value={query} maxLength={200} onChange={event=>setQuery(event.target.value)} placeholder="搜索画像标签或内容"/><Select aria-label="画像状态" value={filter} onChange={setFilter} options={[
      {value:'all',label:'全部状态'},{value:'candidate',label:'待复核'},{value:'active',label:'已接受'},
      {value:'rejected',label:'已拒绝'},{value:'stale',label:'已失效'},
    ]}/></div>
    <List loading={personas.isFetching} dataSource={(personas.data?.items??[]).filter(item=>`${item.label} ${item.statement}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))} locale={{emptyText:<Empty description={query?"当前已加载画像中没有匹配项":"尚无 L3 画像依据或候选"}/>}}
      renderItem={item=><List.Item className="memory-item" onClick={() => setSelectedId(item.id)} actions={[<Button key="open" type="link" onClick={event=>{event.stopPropagation();setSelectedId(item.id);}}>查看证据</Button>]}>
        <List.Item.Meta title={<Space wrap><span>{item.label}</span><Tag>{kindName[item.kind]}</Tag><Tag color={item.basis==='user_declared'?'blue':'purple'}>{basisName[item.basis]}</Tag><Tag color={stateColor[item.status]}>{stateName[item.status]}</Tag></Space>}
          description={<><p className="scenario-summary">{item.statement}</p><small>{displayTime(item.generated_at)} · 修订 {item.revision}</small></>}/></List.Item>}/>
  </>;

  return <><AppShell subtitle="可复核的用户画像" className="persona-shell" sidebar={sidebar}>
    <PageHeader eyebrow="长期记忆" title="用户画像（L3）" description="在一份持续累积的画像中归纳稳定偏好、习惯与规划，并保留每项认识的证据。" meta={config.data?.database??'未指定记忆库'} action={<Button loading={personas.isFetching||profile.isFetching} onClick={() => void Promise.all([
        queryClient.invalidateQueries({queryKey:['personas']}),queryClient.invalidateQueries({queryKey:['persona-profile']}),
      ])}>刷新</Button>}/>
    <Alert className="mode-card" type="info" showIcon title="这里是一份持续累积的统一用户画像"
      description="页面按栏目汇总所有已接受的 L3 认识；底层仍保存独立断言和 L1/L2→L0 来源，便于逐项纠正、失效和审计。它不是助手角色，当前也尚未用于回答。"/>

    {!canManage&&config.data?.configured&&<Alert type="warning" showIcon title="当前进程没有开启 L3 管理权限" description="通过新版日常启动面板启动可开放候选与复核；只读浏览不受影响。"/>}
    <DataWorkspace label="画像工作区" activeKey={workspace} onChange={setWorkspace} items={[
      {key:'profile',label:'统一画像',children:profilePane},
      {key:'evidence',label:`画像依据与候选（${personas.data?.total??0}）`,children:<>{evidencePane}<p className="subtle">当前状态读取最多 100 条；搜索仅筛选已加载内容。</p></>},
      {key:'consolidation',label:'整理状态',children:<>    <ConsolidationStatusCard stage="l2_to_l3" enabled={ready&&config.data?.configured===true}/></>},
    ]}/>
    <p role="status">{config.error?derivedMemoryFailure(config.error,'read'):profile.error?derivedMemoryFailure(profile.error,'read'):personas.error?derivedMemoryFailure(personas.error,'read'):notice}</p>
  </AppShell>

  <Drawer title="L3 画像详情" size="large" open={Boolean(selectedId)} onClose={closeDetail} loading={detail.isFetching}>
    {detail.isError&&<Alert type="error" showIcon title="无法打开这条 L3 画像" description="记录可能已经失效、被移除，或记忆服务暂不可用。关闭详情后可刷新画像列表；页面没有自动重试或修改数据。"/>}
    {detail.data&&<><Space wrap><h2>{detail.data.label}</h2><Tag>{kindName[detail.data.kind]}</Tag><Tag color={detail.data.basis==='user_declared'?'blue':'purple'}>{basisName[detail.data.basis]}</Tag><Tag color={stateColor[detail.data.status]}>{stateName[detail.data.status]}</Tag></Space>
      <p className="detail-content">{detail.data.statement}</p>
      <Descriptions column={1} size="small" bordered items={[
        {key:'subject',label:'主体',children:detail.data.subject_id},{key:'generated',label:'生成时间',children:displayTime(detail.data.generated_at)},
        {key:'validFrom',label:'现实开始时间',children:displayTime(detail.data.valid_from)},{key:'validTo',label:'现实结束时间',children:displayTime(detail.data.valid_to)},
        {key:'sourceCount',label:'证据覆盖',children:detail.data.audit?`${detail.data.audit.source_count} 个来源 · ${detail.data.audit.source_message_count} 条用户原话 · ${detail.data.audit.observation_day_count} 个观察日`:'审计缺失'},
        {key:'review',label:'复核来源',children:detail.data.review
          ? `${detail.data.review.reviewer_type==='policy'?'自动策略':'用户确认'} · ${displayTime(detail.data.review.reviewed_at)}`
          : '尚未复核'},
        ...(detail.data.review?.reviewer_type==='policy'?[{key:'policy',label:'自动策略依据',children:`${detail.data.review.policy_version} · ${detail.data.review.decision_reason}`}]:[]),
        {key:'revision',label:'修订号',children:String(detail.data.revision)},
      ]}/>
      <h3>L1/L2 来源与 L0 原话</h3>{detail.data.sources.map(source=><Card className="source-card" key={`${source.source_layer}:${source.source_id}`} size="small" title={`${source.source_layer.toUpperCase()} · ${source.source_id}`} extra={<Tag color={source.active?'green':'red'}>{source.active?'仍有效':'已失效'}</Tag>}>
        <p>{source.source_content_snapshot}</p>{source.current_content!==source.source_content_snapshot&&<p className="memory-warning">当前内容与创建时快照不同：{source.current_content??'来源已不存在或失效'}</p>}
        <details><summary>查看用户 L0 原话（{source.l0_sources.length}）</summary>{source.l0_sources.map(item=><blockquote key={item.id}><p>{item.content}</p><small>{item.source_type} · {displayTime(item.created_at)}</small></blockquote>)}</details>
      </Card>)}
      {(detail.data.replaces??[]).length>0&&<><h3>准备取代的旧画像</h3><List size="small" dataSource={detail.data.replaces} renderItem={item=><List.Item>{item.related?.statement??item.replaced_persona_id} · {item.applied_at?'已随本画像接受而取代':'等待本候选复核'}</List.Item>}/></>}
      {(detail.data.replaced_by??[]).length>0&&<><h3>已由新画像取代</h3><List size="small" dataSource={detail.data.replaced_by} renderItem={item=><List.Item>{item.related?.statement??item.candidate_persona_id} · {displayTime(item.applied_at)}</List.Item>}/></>}
      {detail.data.status==='candidate'&&<Space><Button type="primary" disabled={!canManage} onClick={() => setReviewDecision('accepted')}>接受</Button><Button danger disabled={!canManage} onClick={() => setReviewDecision('rejected')}>拒绝</Button></Space>}
      {detail.data.status==='active'&&<Button disabled={!canManage} onClick={openReplacement}>更新这项画像</Button>}
      <h3>来源失效记录</h3>{detail.data.lifecycle_events.length?<List size="small" dataSource={detail.data.lifecycle_events} renderItem={event=><List.Item>{event.source_layer.toUpperCase()} {event.source_id} · {event.action} · {displayTime(event.occurred_at)}</List.Item>}/>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无来源失效事件"/>}
    </>}
  </Drawer>

  <Modal title={replacementIds.length?'创建画像更新候选':'新建 L3 用户画像候选'} open={creating} okText="创建待复核候选" cancelText="取消" confirmLoading={createCandidate.isPending}
    okButtonProps={{disabled:!label.trim()||!statement.trim()||sources.length<1||!validRange}} onCancel={() => setCreating(false)} onOk={() => createCandidate.mutate()}>
    <Alert type={basis==='system_inferred'?'warning':'info'} showIcon title={basis==='system_inferred'?'系统推断需要跨记录证据':'用户声明必须能回到用户原话'}
      description={basis==='system_inferred'?'服务端强制要求至少 2 个来源、3 条不同用户 L0、2 个观察日；达到门槛也不等于推断必然正确。':'至少选择一个能直接支持这条声明的 L1 或已接受 L2，创建后仍需复核。'}/>
    {replacementIds.length>0&&<Alert type="warning" showIcon title="这是追加＋取代，不是原地覆盖" description="新内容先作为候选保存；只有接受后，旧画像才会失效并保留取代关系。拒绝候选不会改变旧画像。"/>}
    <label htmlFor="persona-kind">画像类型</label><Select id="persona-kind" className="wide" disabled={replacementIds.length>0} value={kind} onChange={setKind} options={Object.entries(kindName).map(([value,label])=>({value,label}))}/>
    <label htmlFor="persona-basis">依据性质</label><Select id="persona-basis" className="wide" value={basis} onChange={value=>{setBasis(value);setDraftOrigin('manual');}} options={Object.entries(basisName).map(([value,label])=>({value,label}))}/>
    <label htmlFor="persona-label">简短标签</label><Input id="persona-label" value={label} maxLength={120} onChange={event=>setLabel(event.target.value)} placeholder="例如：建议前先倾听"/>
    <label htmlFor="persona-statement">画像断言</label><Input.TextArea id="persona-statement" value={statement} maxLength={1000} rows={4} onChange={event=>setStatement(event.target.value)} placeholder="一次只写一条可独立核对的认识"/>
    <label htmlFor="persona-sources">证据来源</label><Select id="persona-sources" aria-label="画像证据来源" mode="multiple" className="wide" value={sources} onChange={setSources} optionFilterProp="label" options={options}/>
    <Space direction="vertical" className="wide">
      <Button disabled={!config.data?.persona_model_preview_available||sources.length<1} onClick={()=>setConfirmingModel(true)}>让模型提出整理建议</Button>
      <small>{config.data?.persona_model_preview_available
        ? `调用前会再次确认；当前模型：${config.data.persona_model??'未标记'}`
        : '当前启动方式没有可用的 L3 草稿模型，仍可手工填写。'}</small>
      {draftOrigin!=='manual'&&<Tag color="purple">当前内容来自模型整理建议，已允许人工修改</Tag>}
    </Space>
    <label htmlFor="persona-valid-from">现实开始时间（可选）</label><Input id="persona-valid-from" type="datetime-local" value={validFrom} onChange={event=>setValidFrom(event.target.value)}/>
    <label htmlFor="persona-valid-to">现实结束时间（可选）</label><Input id="persona-valid-to" type="datetime-local" value={validTo} onChange={event=>setValidTo(event.target.value)}/>
    {!validRange&&<Alert type="error" showIcon title="结束时间不能早于开始时间"/>}
  </Modal>

  <Modal title="确认让模型整理所选记忆" open={confirmingModel} centered width={620} zIndex={1400}
    confirmLoading={previewCandidate.isPending} okText="生成不落库建议" cancelText="取消"
    onCancel={()=>!previewCandidate.isPending&&setConfirmingModel(false)}
    onOk={()=>previewCandidate.mutate()}>
    <p>将发送 {sources.length} 个已选 L1/L2 的内容、它们向下追溯到的用户 L0 原话和 UTC 观察日期，以及当前有效 L3 的 ID、类型、标签、断言与修订号。</p>
    <p>模型只能建议 ADD、UPDATE 或 NOOP；结果不会自动创建、取代、接受或用于回答，调用失败不会重试。</p>
    <Alert type="warning" showIcon title="个人记忆和当前画像将发送给配置的模型服务" description="只选择支持本次整理的必要来源。所有记忆文本均按不可信数据处理，不能指挥模型或管理接口。"/>
  </Modal>

  <Modal title={reviewDecision==='accepted'?'确认接受 L3 画像':'确认拒绝 L3 候选'} open={Boolean(reviewDecision)} centered width={580} zIndex={1300}
    okText={reviewDecision==='accepted'?'确认接受':'确认拒绝'} cancelText="返回核对" confirmLoading={review.isPending}
    okButtonProps={{danger:reviewDecision==='rejected'}} onCancel={() => !review.isPending&&setReviewDecision(undefined)} onOk={() => reviewDecision&&review.mutate(reviewDecision)}>
    <p><strong>{detail.data?.label}</strong></p><p>{detail.data?.statement}</p>
    <p>{reviewDecision==='accepted'?(detail.data?.replaces?.length?'接受后新画像生效，所列旧画像在同一事务中失效；当前仍不会自动参与回答。':'接受后成为有效画像，但当前切片仍不会自动参与回答。'):'拒绝后保留候选和证据用于审计，不会物理删除，也不会改变拟取代的旧画像。'}</p>
    <p>请确认已经核对 L1/L2 内容、底层 L0 原话和“用户声明/系统推断”标记。</p>
  </Modal></>;
}
