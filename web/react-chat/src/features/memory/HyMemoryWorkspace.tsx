import {useEffect, useId, useMemo, useRef, useState} from 'react';
import {Alert, Button, Checkbox, Descriptions, Drawer, Empty, Input, Modal, Select, Skeleton, Space, Tag} from 'antd';
import {Link, useSearchParams} from 'react-router-dom';
import {ApiError, ChatApi, type EngineItem, type EnginePage, type EngineSource, type EngineStatus, type HyWorkspace, type HyHistory, type HyOperation} from '../../api';
import {MemoryEngineApi} from '../../api/memoryEngine';
import {AppShell, ConsoleNav} from '../../components/AppShell';
import {PageHeader} from '../../components/PageHeader';
import {useUnsavedChanges} from '../../app/UnsavedChanges';
import './hy-memory.css';

type View='items'|'profile'|'activity'|'status';
const views:Array<{key:View;label:string}>=[{key:'items',label:'记忆条目'},{key:'profile',label:'基本画像'},{key:'activity',label:'记录与变化'},{key:'status',label:'处理状态'}];
const kinds:Record<string,string>={l0_basic_info:'基本信息',l1_raw:'原始记录',l2_fact:'记住的事情',l3_summary:'对话摘要',l4_identity:'身份认识（保留层）',l5_knowledge:'知识（保留层）',l6_schema:'认知结构（未启用）',l7_intention:'意图（未启用）'};
const states:Record<string,string>={active:'当前',ACTIVE:'当前',archived:'已归档',pending:'等待处理',running:'处理中',completed:'已完成',uncertain:'结果不确定',failed:'处理失败',not_run:'尚未运行',source_only:'仅保存原话'};
export function memoryTime(value?:string|number|null) {if(value===null||value===undefined||value==='')return '时间未记录';const date=new Date(typeof value==='number'?value*1000:value);return Number.isNaN(date.valueOf())?'时间格式未知':date.toLocaleString('zh-CN');}
function failure(error:unknown) {if(error instanceof ApiError){if(error.status===404)return '这条记录已不存在，或当前引擎无法提供。';if(error.status===409)return '条目或请求状态已变化。请关闭编辑，刷新详情后重新核对。';if(error.status===403)return '当前没有操作权限，或记忆写入已暂停。';if(error.status===501)return '当前引擎尚未接通这项管理能力。';if(error.code==='hy_management_outcome_uncertain')return '操作结果不确定，可能已部分提交。请先核对条目与操作记录，不要重复提交。';}return '读取或操作未完成。可刷新核对；写操作不会自动重试。';}
const sourceSummary=(item:EngineItem)=>item.source_event_ids===null?'来源未提供':item.source_event_ids.length?`${item.source_event_ids.length} 条来源`:'没有关联来源';
function Pager({page,busy,onChange}:{page:EnginePage<unknown>;busy:boolean;onChange:(offset:number)=>void}) {return <nav className="hy-pagination" aria-label="记忆分页"><Button disabled={busy||page.offset===0} onClick={()=>onChange(Math.max(0,page.offset-page.limit))}>上一页</Button><span>{page.items.length?`${page.offset+1}–${page.offset+page.items.length} / ${page.total}`:`本页 0 条 / 共 ${page.total} 条`}</span><Button disabled={busy||page.offset+page.limit>=page.total} onClick={()=>onChange(page.offset+page.limit)}>下一页</Button></nav>;}

export function HyMemoryWorkspace({api,method,capabilities}:{api:ChatApi;method?:string;capabilities?:Record<string,boolean>}) {
  const actionHeading=useId();
  const engine=useMemo(()=>new MemoryEngineApi(api),[api]);
  const isHy=method==='hy_memory_pro_chat';
  const [params,setParams]=useSearchParams();
  const requested=params.get('view');
  const view:View=views.some(v=>v.key===requested)?requested as View:'items';
  const rawOffset=params.get('offset')??'0';
  const offset=/^\d{1,6}$/.test(rawOffset)&&Number(rawOffset)<=100000?Math.floor(Number(rawOffset)/25)*25:0;
  const [page,setPage]=useState<EnginePage<EngineItem>>();
  const [loading,setLoading]=useState(true);
  const [listError,setListError]=useState('');
  const [reload,setReload]=useState(0);
  const [status,setStatus]=useState<EngineStatus>();
  const [workspace,setWorkspace]=useState<HyWorkspace>();
  const [extensionError,setExtensionError]=useState('');
  const [extensionBusy,setExtensionBusy]=useState(isHy);
  const [statusError,setStatusError]=useState('');
  const [query,setQuery]=useState('');
  const [kind,setKind]=useState('all');
  const [detail,setDetail]=useState<EngineItem>();
  const [detailBusy,setDetailBusy]=useState(false);
  const [detailError,setDetailError]=useState('');
  const [detailReload,setDetailReload]=useState(0);
  const [source,setSource]=useState<EngineSource>();
  const [sourceBusy,setSourceBusy]=useState(false);
  const [sourceError,setSourceError]=useState('');
  const [sourceId,setSourceId]=useState('');
  const sourceRequest=useRef(0);
  const [history,setHistory]=useState<HyHistory>();
  const [historyBusy,setHistoryBusy]=useState(false);
  const [historyError,setHistoryError]=useState('');
  const [profile,setProfile]=useState<{item:EngineItem|null}>();
  const profileDetail=params.get('profile_detail')==='1'&&view==='profile';
  const selectedId=params.get('item')??(profileDetail?profile?.item?.item_id??'':'');
  const [profileError,setProfileError]=useState('');
  const [profileBusy,setProfileBusy]=useState(false);
  const [operations,setOperations]=useState<EnginePage<HyOperation>>();
  const [operationsError,setOperationsError]=useState('');
  const [operationsBusy,setOperationsBusy]=useState(false);
  const [itemOperations,setItemOperations]=useState<EnginePage<HyOperation>>();
  const [action,setAction]=useState<'correct'|'delete'>();
  const [draft,setDraft]=useState('');
  const [understood,setUnderstood]=useState(false);
  const [saving,setSaving]=useState(false);
  const [writeError,setWriteError]=useState('');
  const [writeUnknown,setWriteUnknown]=useState(false);
  const [notice,setNotice]=useState('');
  const lock=useRef(false);
  const detailVersion=useRef(0);
  useUnsavedChanges(Boolean(action==='correct'&&draft!==detail?.content),'有未保存的记忆纠正。');

  function navigate(patch:Record<string,string|undefined>) {setParams(previous=>{const next=new URLSearchParams(previous);for(const [key,value] of Object.entries(patch)){if(value===undefined)next.delete(key);else next.set(key,value);}return next;});}
  useEffect(()=>{let current=true;setStatusError('');setExtensionError('');setExtensionBusy(isHy);void engine.status().then(value=>{if(current)setStatus(value);}).catch(error=>{if(current)setStatusError(failure(error));});if(isHy)void engine.workspace().then(value=>{if(current)setWorkspace(value);}).catch(error=>{if(current){setWorkspace(undefined);setExtensionError(failure(error));}}).finally(()=>{if(current)setExtensionBusy(false);});return()=>{current=false;};},[engine,isHy,reload]);
  useEffect(()=>{if(view!=='items')return;let current=true;setLoading(true);setPage(undefined);setListError('');setQuery('');setKind('all');if(capabilities?.listing===false){setListError('当前引擎不提供条目列表。');setLoading(false);return;}void engine.items(offset).then(value=>{if(current)setPage(value);}).catch(error=>{if(current)setListError(failure(error));}).finally(()=>{if(current)setLoading(false);});return()=>{current=false;};},[engine,offset,reload,view,capabilities?.listing]);
  useEffect(()=>{let current=true;detailVersion.current++;sourceRequest.current++;setDetail(undefined);setSource(undefined);setSourceError('');setSourceId('');setSourceBusy(false);setHistory(undefined);setHistoryError('');setHistoryBusy(false);setItemOperations(undefined);setDetailError('');if(!selectedId)return;if(profileDetail&&profile?.item){setDetail(profile.item);setDetailBusy(false);return;}setDetailBusy(true);if(selectedId.length>256||/[\u0000-\u001f\u007f]/.test(selectedId)){setDetailError('记忆链接格式无效。');setDetailBusy(false);return;}void engine.item(selectedId).then(value=>{if(current)setDetail(value);}).catch(error=>{if(current)setDetailError(failure(error));}).finally(()=>{if(current)setDetailBusy(false);});if(workspace?.operations)void engine.operations(0,selectedId).then(value=>{if(current)setItemOperations(value);}).catch(()=>{if(current)setItemOperations(undefined);});return()=>{current=false;};},[engine,selectedId,detailReload,workspace?.operations,profileDetail,profile]);
  useEffect(()=>{if(view!=='profile'||!workspace?.profile)return;let current=true;setProfile(undefined);setProfileError('');setProfileBusy(true);void engine.profile().then(value=>{if(current)setProfile(value);}).catch(error=>{if(current)setProfileError(failure(error));}).finally(()=>{if(current)setProfileBusy(false);});return()=>{current=false;};},[engine,view,workspace?.profile,reload]);
  useEffect(()=>{if(view!=='activity'||!workspace?.operations)return;let current=true;setOperations(undefined);setOperationsError('');setOperationsBusy(true);void engine.operations(offset).then(value=>{if(current)setOperations(value);}).catch(error=>{if(current)setOperationsError(failure(error));}).finally(()=>{if(current)setOperationsBusy(false);});return()=>{current=false;};},[engine,view,offset,workspace?.operations,reload]);

  async function showSource(id:string) {const version=++sourceRequest.current;setSourceId(id);setSource(undefined);setSourceError('');setSourceBusy(true);try{const value=await engine.source(id);if(version===sourceRequest.current)setSource(value);}catch(error){if(version===sourceRequest.current)setSourceError(failure(error));}finally{if(version===sourceRequest.current)setSourceBusy(false);}}
  async function showHistory() {if(!detail||historyBusy)return;const version=detailVersion.current;setHistoryBusy(true);setHistoryError('');try{const value=await engine.history(detail.item_id);if(version===detailVersion.current)setHistory(value);}catch(error){if(version===detailVersion.current)setHistoryError(failure(error));}finally{if(version===detailVersion.current)setHistoryBusy(false);}}
  function beginAction(value:'correct'|'delete') {if(!detail)return;setDraft(detail.content);setAction(value);setUnderstood(false);setWriteError('');setWriteUnknown(false);}
  async function save() {if(lock.current||!detail||!action||writeUnknown)return;lock.current=true;setSaving(true);setWriteError('');const id=crypto.randomUUID();try{const result=action==='correct'?await engine.correct(detail.item_id,detail.revision,draft.trim(),id):await engine.delete(detail.item_id,detail.revision,id);if(result.state!=='completed'||result.request_id!==id||result.platform_sources_preserved!==true)throw new Error('not confirmed');setNotice(`${action==='correct'?'纠正已完成':'引擎条目已删除'}。平台原话保留。操作编号：${result.request_id}`);setAction(undefined);if(action==='delete')navigate({item:undefined});else setDetailReload(v=>v+1);setReload(v=>v+1);}catch(error){setWriteError(`${failure(error)} 操作编号：${id}`);setWriteUnknown(true);setDetailReload(v=>v+1);}finally{lock.current=false;setSaving(false);}}
  const visible=page?.items.filter(item=>(kind==='all'||item.kind===kind)&&item.content.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))??[];
  const blocked=writeUnknown||itemOperations?.items.some(item=>item.state==='uncertain'||item.state==='running');
  const manageable=detail&&['l2_fact','l3_summary'].includes(detail.kind);
  const sources=detail?.source_event_ids??[];
  const correctionSources=itemOperations?.items.filter(item=>item.action==='correct'&&item.state==='completed')??[];

  return <><AppShell subtitle="核对每一条长期记忆" className="memory-shell hy-shell" sidebar={<ConsoleNav active="memories" legacyPath="/memories-legacy" memoryEngine={isHy?'hy':undefined}/> }>
    <PageHeader eyebrow="长期记忆" title="我的记忆" description="看看智慧圆屏记住了什么，沿着来源核对，再决定是否更正。" action={<Button aria-label="刷新当前视图" onClick={()=>{setReload(v=>v+1);if(selectedId)setDetailReload(v=>v+1);}} disabled={saving}>刷新</Button>}/>
    <div className="hy-engine-line"><strong>{isHy?'Hy-Memory':method??'独立记忆引擎'}</strong><span>{status?`记忆写入${status.write_enabled?'开启':'暂停'}，回答时${status.use_enabled?'使用':'不使用'}记忆`:'正在核对引擎状态'}</span><Link to="/chat-react">回到聊天</Link></div>
    {notice&&<Alert type="success" showIcon closable onClose={()=>setNotice('')} title={notice}/>}
    <nav className="hy-views" aria-label="记忆管理视图">{views.map(item=><button key={item.key} type="button" aria-current={view===item.key?'page':undefined} onClick={()=>navigate({view:item.key,offset:undefined,item:undefined,profile_detail:undefined})}>{item.label}</button>)}</nav>
    {statusError&&<Alert type="warning" showIcon title="状态读取未完成" description={statusError}/>}
    {view==='items'&&<section aria-labelledby="hy-items-heading" className="hy-book">
      <div className="hy-section-heading"><div><h2 id="hy-items-heading">记住的内容</h2><p>当前有效条目，按记录时间从新到旧。{page?`共 ${page.total} 条。`:''}</p></div><span className="hy-scope">{page?`本页 ${page.items.length} 条`:'等待读取'}</span></div>
      <div className="hy-filters"><div><label htmlFor="hy-query">在本页查找</label><Input id="hy-query" placeholder="输入正文关键词" value={query} maxLength={200} allowClear onChange={e=>setQuery(e.target.value)} disabled={loading||!page}/></div><div><label htmlFor="hy-kind">本页内容类型</label><Select id="hy-kind" aria-label="本页内容类型" value={kind} onChange={setKind} disabled={loading||!page} options={[{value:'all',label:'全部类型'},...Array.from(new Set(page?.items.map(i=>i.kind))).map(value=>({value,label:kinds[value]??'引擎条目'}))]}/></div></div>
      <p className="hy-hint">仅筛选本页，翻页后重置。全库正文检索尚不可用。</p>
      {loading?<div role="status" aria-label="正在读取记忆"><Skeleton active paragraph={{rows:5}}/></div>:listError?<Alert type="error" showIcon title="记忆列表读取失败" description={listError} action={<Button onClick={()=>setReload(v=>v+1)}>重新读取列表</Button>}/>:page&&<>
        {visible.length?<ol className="hy-entry-list">{visible.map(item=><li key={item.item_id}><div className="hy-entry-copy"><span className="hy-kind">{kinds[item.kind]??'引擎条目'}</span><p>{item.content.length>180?`${item.content.slice(0,180)}…`:item.content}</p>{item.content.length>180&&<span className="hy-hint">长内容，详情中查看全文</span>}<div className="hy-entry-meta"><span>{memoryTime(item.recorded_at)}</span><span>{sourceSummary(item)}</span>{item.state&&item.state.toUpperCase()!=='ACTIVE'&&<Tag>{states[item.state]??'引擎自定状态'}</Tag>}</div></div><Button onClick={()=>navigate({item:item.item_id})}>查看详情</Button></li>)}</ol>:<Empty description={page.items.length?'本页没有符合筛选条件的记忆':'这一页还没有记忆条目'}><p>{page.total?'可清除筛选或返回上一页查看。':'从今后的对话开始积累。原有记忆库仍独立保留。'}</p>{(query||kind!=='all')&&<Button onClick={()=>{setQuery('');setKind('all');}}>清除本页筛选</Button>}</Empty>}
        {page.items.length>0&&page.offset+page.items.length<Math.min(page.total,page.offset+page.limit)&&<Alert type="warning" title="这一页只返回了部分条目" description="总数和返回范围以引擎响应为准，可刷新核对；未把缺少的条目当作已删除。"/>}
        <Pager page={page} busy={loading} onChange={value=>navigate({offset:String(value)})}/>
      </>}
    </section>}
    {view==='profile'&&<section className="hy-book" aria-labelledby="hy-profile-heading"><div className="hy-section-heading"><div><h2 id="hy-profile-heading">对你的基本认识</h2><p>由引擎汇总的画像仍需沿来源核对，不自动当作你确认的事实。</p></div></div>{extensionBusy?<Skeleton active/>:!workspace?.profile?<Empty description="基本画像暂不可读取"><p>{extensionError||'画像 API 只按用户隔离。当前尚未证明它与本空间的助手及来源范围一致。'}</p></Empty>:profileBusy?<Skeleton active/>:profileError?<Alert type="error" title="基本画像读取失败" description={profileError}/>:profile?.item?<><p className="hy-profile-content">{profile.item.content}</p><p className="hy-hint">{sourceSummary(profile.item)}</p><Button onClick={()=>navigate({profile_detail:'1',item:undefined})}>核对画像详情与来源</Button></>:<Empty description="尚未形成基本画像"><p>继续自然对话后再查看，不需要手动建立空画像。</p></Empty>}</section>}
    {view==='activity'&&<section className="hy-book" aria-labelledby="hy-activity-heading"><div className="hy-section-heading"><div><h2 id="hy-activity-heading">记录与变化</h2><p>这里记录你在管理页发起的动作。引擎内部变化需在单条记忆详情中查看，二者不等同。</p></div></div>{extensionBusy?<Skeleton active/>:!workspace?.operations?<Empty description="操作记录尚未接通"><p>{extensionError||'当前引擎未提供可追溯的管理操作记录。'}</p></Empty>:operationsBusy?<Skeleton active/>:operationsError?<Alert type="error" title="操作记录读取失败" description={operationsError}/>:operations&&<>{operations.items.length?<ol className="hy-operation-list">{operations.items.map(item=><li key={item.request_id}><div><strong>{item.action==='correct'?'纠正记忆':'删除引擎条目'}</strong><Tag color={item.state==='uncertain'?'warning':item.state==='completed'?'success':'processing'}>{states[item.state]}</Tag><p>{memoryTime(item.occurred_at)}</p><code>{item.request_id}</code>{item.state==='uncertain'&&<p>可能已经部分提交，请先核对；不要重复操作。</p>}</div><Button onClick={()=>navigate({item:item.item_id})}>核对条目</Button></li>)}</ol>:<Empty description="还没有管理操作记录"/>}<Pager page={operations} busy={operationsBusy} onChange={value=>navigate({offset:String(value)})}/></>}</section>}
    {view==='status'&&<section className="hy-book" aria-labelledby="hy-status-heading"><div className="hy-section-heading"><div><h2 id="hy-status-heading">处理状态</h2><p>区分原话保存、引擎处理与回答使用，不把历史运行成功当作本次结果。</p></div></div>{status?<><Descriptions column={1} items={[{key:'write',label:'从新对话积累记忆',children:status.write_enabled?'开启':'暂停（原话仍可能由平台归档）'},{key:'use',label:'回答时使用记忆',children:status.use_enabled?'开启':'暂停'},{key:'wait',label:'等待设备完成回执',children:status.deferred_observation?.supported?String(status.deferred_observation.awaiting_completion):'当前方法未提供'},{key:'queue',label:'运行或排队',children:status.deferred_observation?.supported?String(status.deferred_observation.running_or_queued):'当前方法未提供'},{key:'last',label:'最近处理结果',children:states[status.deferred_observation?.last_result.state??'']??'尚未提供'}]}/>{status.deferred_observation?.last_result.warning_code&&<p className="hy-hint">诊断代码：{status.deferred_observation.last_result.warning_code}</p>}</>:<p>{statusError||'正在读取本次运行状态…'}</p>}<h3>当前管理范围</h3><p>列表与详情：{capabilities?.listing&&capabilities.detail?'已接通':'以引擎返回能力为准'}。纠正与删除：{workspace?.correction||workspace?.deletion?'受控单条操作已接通':'尚未启用'}。</p>{extensionError&&<Alert type="info" title="扩展管理尚未接通" description={extensionError}/>}<p className="hy-hint">Hy 的身份认识、知识保留层可如实阅读；图谱、意图和深层认知加工未启用。旧引擎的场景、画像与批量清库操作不套用到这里。</p></section>}
  </AppShell>
  <Drawer title="记忆详情" open={Boolean(selectedId)} onClose={()=>{if(!saving&&!action)navigate({item:undefined,profile_detail:undefined});}} size="large" className="hy-detail" maskClosable={!saving&&!action} keyboard={!saving&&!action}>
    {detailBusy?<Skeleton active/>:detailError?<Alert type="error" title="详情读取失败" description={detailError} action={<Button onClick={()=>setDetailReload(v=>v+1)}>重新读取详情</Button>}/>:detail&&<>
      <Tag>{kinds[detail.kind]??'引擎条目'}</Tag><p className="hy-detail-content">{detail.content}</p><Descriptions column={1} size="small" items={[{key:'time',label:'记录时间',children:memoryTime(detail.recorded_at)},{key:'valid',label:'事实有效区间',children:detail.valid_from||detail.valid_to?`${memoryTime(detail.valid_from)} 至 ${memoryTime(detail.valid_to)}`:'引擎未提供，不从记录时间推断'},{key:'state',label:'当前状态',children:detail.state?(states[detail.state]??detail.state):'引擎未提供'}]}/>
      <section className="hy-detail-section"><h3>依据是什么</h3><p>{sourceSummary(detail)}</p>{sources.length>0&&<><label htmlFor="hy-source">选择一条来源回看</label><select id="hy-source" aria-label="选择一条来源回看" className="hy-source-picker" value={sourceId} onChange={event=>void showSource(event.target.value)}><option value="" disabled>选择来源编号</option>{sources.map(id=><option key={id} value={id}>{id}</option>)}</select></>}
        {correctionSources.length>0&&<details><summary>查看管理纠正的明确指令来源（本页 {correctionSources.length} 条）</summary><p className="hy-hint">这些来源由平台操作记录关联；不表示 SDK 已改写原始来源字段。</p>{correctionSources.map(item=><Button key={item.request_id} onClick={()=>void showSource(item.source_event_id)}>回看纠正指令 {memoryTime(item.occurred_at)}</Button>)}</details>}
        {sourceBusy?<p role="status">正在读取选中的原话…</p>:sourceError?<Alert type="warning" title="这条来源未读到" description={sourceError} action={<Button onClick={()=>void showSource(sourceId)}>重读这一条来源</Button>}/>:source&&<blockquote className="hy-source"><strong>{source.role==='user'?'用户原话':source.role==='assistant'?'助手原话（不是用户事实）':'原始角色未知'}</strong><p>{source.content}</p><footer>{memoryTime(source.occurred_at)}<span>{states[source.state]??'处理状态未知'}</span></footer></blockquote>}
        {detail.source_event_ids===null&&<p className="hy-hint">引擎没有提供来源关联。不能据此推断没有原话，也不能补造来源。</p>}
      </section>
      <section className="hy-detail-section"><h3>这条记忆怎样变化</h3>{workspace?.history&&!profileDetail?<><Button aria-busy={historyBusy} onClick={()=>void showHistory()}>{historyBusy?'正在读取变化记录…':history?'刷新这条变化记录':'读取这条变化记录'}</Button>{historyError&&<Alert type="error" title="变化记录读取失败" description={historyError}/>} {history&&<>{history.items.length?<ol className="hy-history">{history.items.map((item,index)=><li key={index}><strong>{item.event??'引擎变更'}</strong><span>{memoryTime(item.created_at)}</span>{item.old_memory&&<p>此前：{item.old_memory}</p>}{item.new_memory&&<p>此后：{item.new_memory}</p>}</li>)}</ol>:<p>未读到变化记录。可能尚无变化，也可能引擎未开启历史记录。</p>}{history.limited&&<p>仅展示最近 100 条返回记录。</p>}</>}</>:<p className="hy-hint">引擎变化历史尚未接通。当前正文和记录时间不能替代历史。</p>}</section>
      <section className="hy-detail-section"><h3>发现记错了</h3>{blocked&&<Alert type="warning" title="这条记忆有未确认操作" description="先核对当前内容和操作记录，暂不再次提交。"/>}{manageable&&(workspace?.correction||workspace?.deletion)?<><p>按唯一引擎拥有者串行核对修订后执行。操作失败可能部分提交，不提供自动回滚。</p><Space wrap>{workspace.correction&&<Button onClick={()=>beginAction('correct')} disabled={saving||blocked}>纠正这条记忆</Button>}{workspace.deletion&&<Button danger onClick={()=>beginAction('delete')} disabled={saving||blocked}>删除这条记忆</Button>}</Space></>:<p className="hy-hint">{manageable?'当前还不能安全提交纠正或删除：需要管理接线、唯一拥有者修订核对与写入权限。':'这类条目目前仅供核对；不直接修改汇总画像、原始记录或保留层。'}保留当前内容，接通后再操作。</p>}</section>
      <details className="hy-technical"><summary>查看引擎标识与修订</summary><dl><dt>条目编号</dt><dd>{detail.item_id}</dd><dt>原生类型</dt><dd>{detail.kind}</dd><dt>当前修订指纹</dt><dd>{detail.revision}</dd></dl></details>
    </>}
  </Drawer>
  <Modal aria-labelledby={actionHeading} title={<span id={actionHeading}>{action==='correct'?'纠正这条记忆':'删除这条引擎记忆'}</span>} open={Boolean(action)} okText={action==='correct'?'保存纠正':'确认删除条目'} cancelText="取消" confirmLoading={saving} mask={{closable:!saving}} keyboard={!saving} closable={!saving} onCancel={()=>{if(!saving)setAction(undefined);}} onOk={()=>void save()} okButtonProps={{danger:action==='delete',disabled:saving||writeUnknown||!detail||!understood||(action==='correct'&&(!draft.trim()||draft.trim()===detail?.content||draft.length>1000))}}>
    {action==='correct'?<><p>把这条记忆改成你确认的内容。这次明确指令会保存为用户来源。</p><label htmlFor="hy-correction">正确的内容</label><Input.TextArea id="hy-correction" value={draft} onChange={event=>setDraft(event.target.value)} maxLength={1000} showCount autoSize={{minRows:4,maxRows:10}} disabled={saving}/></>:<><p>仅删除选中的引擎条目。平台原话、历史及备份保留；这不是全部隐私数据擦除，也不承诺它不会从后续对话再次形成。</p><p className="hy-delete-preview">{detail?.content}</p></>}
    <Checkbox checked={understood} onChange={event=>setUnderstood(event.target.checked)} disabled={saving}>我已核对这条记忆，理解操作范围和失败可能部分提交</Checkbox>{writeError&&<Alert type="error" title="操作未确认完成" description={writeError}/>} {writeUnknown&&<p role="status">结果未确认，已禁止重复提交。关闭此窗口后到“记录与变化”核对操作。</p>}
  </Modal></>;
}
