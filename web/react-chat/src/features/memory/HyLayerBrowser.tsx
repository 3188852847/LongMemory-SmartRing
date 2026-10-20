import {useLayoutEffect,useRef,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Alert,Button,Drawer,Empty,Skeleton,Tag} from 'antd';
import {useSearchParams} from 'react-router-dom';
import {ApiError,ChatApi} from '../../api';
import {MemoryEngineApi} from '../../api/memoryEngine';
import {HY_LAYER_STATES,HyLayerContractError,hyLayerIdentifier,type HyLayerId,type HyLayerRead,type HyLayerState,type HyStoredRecord} from '../../api/hyLayerData';
import {useMemoryEngine} from '../../app/MemoryEngineProvider';
import {memoryTime} from './HyMemoryWorkspace';
import './hy-layer-data.css';

const api=new MemoryEngineApi(new ChatApi());
const states:Record<string,string>={all:'全部状态',active:'有效',superseded:'已被取代',negated:'已否定',conflicted:'有冲突',shadow:'影子',archived:'已归档'};
const generation={configured:'当前生成已接入',disabled:'当前生成已关闭',historical:'仅历史兼容',reserved:'保留层',unknown:'生成配置未知'};
const reasons:Record<string,string>={
  profile_scope_unproven:'尚未证明基本画像属于当前拥有者与来源范围，不能读取或补用其他范围字段。',
  profile_history_limit:'原生版本超过安全聚合上限，无法给出完整画像；没有把部分字段当完整结果。',
  profile_fields_limit:'画像字段超过有界读取限制，未返回可能不完整的聚合。',
  profile_head_unavailable:'未能确认画像版本链头，当前无法安全聚合。',
  storage_backend_unavailable:'当前存储装配尚不支持这项有界读取，没有回落到其他库。',
  graph_store_not_open:'图库没有打开。这里只显示当前向量存储范围，不能据此判定图中有无记录。',
};
function failure(error:unknown) {
  if(error instanceof HyLayerContractError)return error.message;
  if(error instanceof ApiError){
    if(error.code==='hy_layer_data_busy')return '引擎正在处理其他任务，本次未读取。请稍后手动重试。';
    if(error.status===404)return '该记录不存在，或不属于当前层和读取范围；未从其他范围补读。';
    if(error.status===501)return '当前服务尚不支持逐层读取，请核对已部署版本。';
    if(error.status===401)return '本机会话已失效，重新连接后再读取。';
  }
  return '本次读取失败，没有将失败解释为空层。可手动重试。';
}
function ReadBoundary({data}:{data:HyLayerRead}) {
  return <div className="hy-layer-boundary">
    <div className="hy-layer-badges"><Tag>{generation[data.generation_state]}</Tag><span>{data.read_status==='readable'?'可读取':data.read_status==='partial'?'部分范围可读':'当前不可读取'}</span><span>读取于 {memoryTime(data.observed_at)}</span></div>
    {data.read_status!=='readable'&&<Alert type="warning" showIcon title={data.read_status==='partial'?'只覆盖部分存储范围':'当前无法读取本层内容'} description={<>{data.reason_code?(reasons[data.reason_code]??'当前读取范围受限，具体原因见返回代码。'):'接口没有提供可安全展示的内容。'}{data.reason_code&&<small className="hy-layer-reason">{data.reason_code}</small>}</>}/>}
  </div>;
}
function RecordTimes({item}:{item:HyStoredRecord}) {
  return <dl className="hy-layer-times"><div><dt>存储时间</dt><dd>{memoryTime(item.recorded_at)}</dd></div><div><dt>记忆时间</dt><dd>{memoryTime(item.memory_at)}</dd></div><div><dt>生效</dt><dd>{memoryTime(item.valid_from)}</dd></div><div><dt>失效</dt><dd>{memoryTime(item.valid_until)}</dd></div></dl>;
}
function ProfileFields({item,onVersion}:{item:HyStoredRecord;onVersion:(id:string)=>void}) {
  return <dl className="hy-profile-fields">{Object.entries(item.basic_info??{}).map(([key,value])=>{
    const origin=item.field_sources?.[key];
    return <div key={key}><dt>{key}</dt><dd><p>{value===null?'空值（null）':value===''?'空文本（已保存）':typeof value==='boolean'?(value?'是':'否'):String(value)}</p>{origin?<>{origin.native_id?<Button type="link" onClick={()=>onVersion(origin.native_id!)}>核对该字段的原生版本</Button>:<small>该字段原生版本来源未提供</small>}<small>{origin.source_event_ids===null?'该字段的平台来源未提供':`该字段关联 ${origin.source_event_ids.length} 条平台来源`}</small></>:<small>该字段来源未提供</small>}</dd></div>;
  })}</dl>;
}

/** 只在用户打开所选层后读取；页、详情和来源各自有界，失败不复用另一层内容。 */
export function HyLayerBrowser({layer,title,revealRequest=0}:{layer:HyLayerId;title:string;revealRequest?:number}) {
  const engine=useMemoryEngine();
  const heading=useRef<HTMLHeadingElement>(null);
  const previousReveal=useRef(revealRequest);
  useLayoutEffect(()=>{
    if(previousReveal.current===revealRequest)return;
    previousReveal.current=revealRequest;
    const target=heading.current;
    // 仅响应显式点层。标题仍在屏外时就近进入内容，历史恢复/刷新不触发此滚动。
    if(target&&target.getBoundingClientRect().top>innerHeight-240){target.scrollIntoView({block:'start',behavior:'instant'});target.focus({preventScroll:true});}
  },[revealRequest]);
  const [params,setParams]=useSearchParams();
  const rawOffset=params.get('layer_offset')??'0';
  const offset=/^\d+$/.test(rawOffset)&&Number(rawOffset)<=10000?Math.floor(Number(rawOffset)/20)*20:0;
  const rawState=params.get('layer_state');
  const state:HyLayerState=layer==='l0_basic_info'?'all':HY_LAYER_STATES.includes(rawState as HyLayerState)?rawState as HyLayerState:'all';
  const selected=params.get('layer_item');
  const validId=selected!==null&&hyLayerIdentifier(selected);
  const enabled=engine.kind==='hy'&&engine.phase==='ready';
  const page=useQuery({queryKey:['hy-layer-page',layer,offset,state],queryFn:()=>api.layerPage(layer,offset,state),enabled,retry:false,refetchOnWindowFocus:false,staleTime:15000});
  // 冷开详情链接先完成页读取，避免同一页面并发争抢非阻塞owner读锁。
  const detail=useQuery({queryKey:['hy-layer-detail',layer,selected],queryFn:()=>api.layerDetail(layer,selected!),enabled:enabled&&validId&&!page.isFetching,retry:false,refetchOnWindowFocus:false,staleTime:15000});
  const coordinate=`${layer}:${selected??''}`;
  const [sourceSelection,setSourceSelection]=useState({coordinate:'',id:''});
  const sourceId=sourceSelection.coordinate===coordinate?sourceSelection.id:'';
  function setSourceId(id:string){setSourceSelection({coordinate,id});}
  const source=useQuery({queryKey:['hy-layer-source',layer,selected,sourceId],queryFn:()=>api.source(sourceId),enabled:enabled&&Boolean(sourceId),retry:false,refetchOnWindowFocus:false,staleTime:15000});
  function choose(patch:Record<string,string|undefined>){setParams(previous=>{const next=new URLSearchParams(previous);for(const [key,value] of Object.entries(patch)){if(value===undefined)next.delete(key);else next.set(key,value);}return next;},{preventScrollReset:true});}
  const data=enabled?page.data:undefined;
  const item=enabled?detail.data?.item:undefined;
  const hiddenOld=page.isError||page.isFetching;
  function showVersion(id:string){setSourceId('');choose({layer_item:id});}
  const count=page.isFetching?'正在读取数量':page.isError?'本次数量未确认':data?.total===null?'总数未知':data?.total===undefined?'尚未读取数量':`${data.total} ${layer==='l0_basic_info'?'份聚合画像':'条记录'}`;

  return <section className="hy-layer-browser" aria-labelledby="hy-layer-content-heading">
    <header className="hy-layer-content-heading"><div><h2 id="hy-layer-content-heading" ref={heading} tabIndex={-1}>{title}：已保存内容</h2><p>{layer==='l0_basic_info'?'由完整可读版本合并的基本信息，不是原话列表或链头差异。':layer==='l1_raw'?'SDK 中实际保存的 RAW 原始记忆，独立于平台原话账本。':'读取当前层原生存储记录，保留各自状态与可得关联。'}</p></div><Button disabled={!enabled} loading={page.isFetching} onClick={()=>void page.refetch()}>刷新本层</Button></header>
    <div className="hy-layer-controls"><label>记录状态 <select aria-label="本层记录状态" value={state} disabled={layer==='l0_basic_info'} onChange={event=>choose({layer_state:event.target.value,layer_offset:undefined,layer_item:undefined})}>{HY_LAYER_STATES.map(value=><option key={value} value={value}>{states[value]}</option>)}</select></label><strong>{count}</strong></div>
    {layer==='l0_basic_info'&&<p className="hy-layer-caption">聚合画像不使用状态筛选；聚合份数与原生存储版本数分别展示。</p>}
    {data&&!hiddenOld&&<ReadBoundary data={data}/>}
    <div className="hy-layer-result">
    {enabled&&page.isError&&<Alert type="error" showIcon title="本层内容读取失败" description={failure(page.error)} action={<Button onClick={()=>void page.refetch()}>重试本层</Button>}/>}
    {page.isFetching&&<div role="status" aria-label="正在读取本层内容"><Skeleton active paragraph={{rows:5}}/></div>}
    {!hiddenOld&&data&&data.read_status!=='unavailable'&&<>
      {data.items.length?<ol className="hy-layer-records">{data.items.map(record=><li key={record.item_id}>
        <div className="hy-layer-record-meta"><Tag>{record.kind==='aggregate_profile'?'聚合画像':layer}</Tag><span>{record.status===null?'状态未提供':states[record.status]??record.status}</span><span>{record.is_latest===null?'版本位置未提供':record.is_latest?'当前版本':'历史版本'}</span></div>
        {record.kind==='aggregate_profile'?<><ProfileFields item={record} onVersion={showVersion}/><p>已完整读取 {record.stored_version_count} 个原生版本用于聚合。</p></>:<p className="hy-layer-record-content">{record.content||'（已保存正文为空）'}</p>}
        {record.content_truncated&&<p className="hy-layer-caption">列表正文已截断；原文共 {record.content_chars} 字符，详情最多显示 32768 字符。</p>}
        <RecordTimes item={record}/><Button onClick={()=>showVersion(record.item_id)}>{record.kind==='aggregate_profile'?'核对聚合来源与原生版本':'查看全文与来源'}</Button>
      </li>)}</ol>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={data.data_state==='empty'&&data.coverage==='vdb_complete'?(state==='all'?'本层尚无已保存内容':'当前状态下没有记录'):'当前页没有返回记录，整层是否为空尚不能确认'}><p>{data.coverage==='vdb_only_graph_unopened'?'本次只覆盖向量存储；图库未读，不能当作整层为空。':offset>0?'可返回上一页；空末页不能反推整层没有数据。':'生成关闭或保留层状态本身不证明没有历史数据。'}</p></Empty>}
      <div className="hy-layer-pager" aria-label="本层服务端分页"><span>第 {offset/20+1} 页{data.items.length?` · 当前显示 ${offset+1}–${offset+data.items.length}`:''} · {count}</span><Button disabled={offset===0} onClick={()=>choose({layer_offset:String(Math.max(0,offset-20)),layer_item:undefined})}>上一页</Button><Button disabled={data.has_more!==true||offset>=10000} onClick={()=>choose({layer_offset:String(offset+20),layer_item:undefined})}>下一页</Button></div>
      {data.has_more===null&&<p className="hy-layer-caption">是否还有下一页未知，未猜测分页边界。</p>}
      {offset>=10000&&data.has_more===true&&<p className="hy-layer-caption">已到本次浏览上限，后续记录尚未读取，不代表全层结束。可返回前页或刷新本层。</p>}
      <details className="hy-layer-scope"><summary>读取范围与分页说明</summary><p>{data.count_scope==='aggregate_profile'?'计数单位是当前聚合画像，不是 L0 原生存储行数。':'计数范围限当前拥有者、助手、来源、本层、所选状态和向量存储；未知总数保持未知。'}</p><p>按原生存储顺序有界分页，不是全库时间排序；跨页不冻结快照，期间写入或刷新可能改变后续页。本页没有全库扫描、启用机制或写入操作。</p></details>
    </>}
    </div>
    <Drawer title={`${title}内容详情`} open={selected!==null} onClose={()=>choose({layer_item:undefined})} size="large" className="hy-layer-detail">
      {!enabled&&<Alert type="info" title="当前引擎身份尚未确认，未读取或展示分层详情"/>}
      {!validId&&<Alert type="error" title="记录链接格式无效"/>}
      {detail.isFetching&&<div role="status" aria-label="正在读取分层详情"><Skeleton active/></div>}
      {enabled&&detail.isError&&<Alert type="error" title="详情读取失败" description={failure(detail.error)} action={<Button onClick={()=>void detail.refetch()}>重试详情</Button>}/>}
      {enabled&&detail.data&&!detail.isFetching&&!detail.isError&&<><ReadBoundary data={detail.data}/>{item?<>
        <p className="hy-layer-native-id">{item.kind==='aggregate_profile'?'聚合句柄：profile；实际链头':'原生记录 ID'} <code>{item.native_id}</code></p>
        {item.kind==='aggregate_profile'?<><ProfileFields item={item} onVersion={showVersion}/><p>聚合使用 {item.stored_version_count} 个原生版本；不以链头字段冒充完整画像。</p></>:<p className="hy-layer-record-content">{item.content||'（已保存正文为空）'}</p>}
        {item.content_truncated&&<Alert type="info" title={`详情正文已截断，原文共 ${item.content_chars} 字符`} description="这里只提供有界正文，不能把当前显示当作完整导出。"/>}
        <p>状态：{item.status===null?'未提供':states[item.status]??item.status}；{item.is_latest===null?'版本位置未提供':item.is_latest?'当前版本':'历史版本'}。</p><RecordTimes item={item}/>
        <h3>可得平台来源</h3>{item.source_event_ids===null?<p>来源关联未提供，不能按零来源解释。</p>:item.source_event_ids.length?<label>选择一条平台来源<select aria-label="分层详情平台来源" value={sourceId} onChange={event=>setSourceId(event.target.value)}><option value="">选择后按单条读取</option>{item.source_event_ids.map(id=><option key={id} value={id}>{id}</option>)}</select></label>:<p>该记录没有返回平台来源关联。</p>}
        {sourceId&&<section className="hy-layer-source" aria-label="分层来源正文">{source.isFetching?<Skeleton active/>:source.isError?<Alert type="error" title="单条来源读取失败" description={failure(source.error)}/>:source.data&&<><p>{source.data.role==='user'?'用户原话':source.data.role==='assistant'?'助手回复':source.data.role} · {memoryTime(source.data.occurred_at)}</p><p className="hy-layer-record-content">{source.data.content}</p><p>平台处理状态：{source.data.state??'未提供'}；不等于 SDK 分层记录。</p></>}</section>}
        {item.source_raw_memory_id&&<Button onClick={()=>choose({layer:'l1_raw',layer_item:item.source_raw_memory_id!,layer_state:undefined,layer_offset:undefined})}>核对关联的 Hy RAW 原始记忆</Button>}
        <h3>原生版本关联</h3>{item.supersedes.length+item.superseded_by.length===0?<p>当前记录未返回版本关联；不能据此证明从未变化。</p>:<div className="hy-layer-version-links">{item.supersedes.map(id=><Button key={`old-${id}`} onClick={()=>showVersion(id)}>查看被取代版本 {id}</Button>)}{item.superseded_by.map(id=><Button key={`new-${id}`} onClick={()=>showVersion(id)}>查看后续版本 {id}</Button>)}</div>}{item.version_links_limited&&<p>版本关联已受数量限制，不是完整历史。</p>}
        {detail.data.versions!==null&&<section aria-label="L0 原生存储版本"><h3>L0 原生存储版本</h3><ol className="hy-layer-profile-versions">{detail.data.versions.map(version=><li key={version.item_id}><span>{memoryTime(version.recorded_at)}</span><p>{version.content||'（正文为空）'}</p>{version.content_truncated&&<small>版本摘要已截断，打开后核对有界详情。</small>}<Button onClick={()=>showVersion(version.item_id)}>查看原生版本 {version.item_id}</Button></li>)}</ol></section>}
      </>:detail.data.read_status!=='unavailable'&&<Empty description="没有可显示的记录，未从其他层补读"/>}</>}
      <p className="hy-layer-caption">这里是只读存储内容，不提供纠正/删除，也不因查看而开启生成、检索或模型。</p>
    </Drawer>
  </section>;
}
