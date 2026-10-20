import {useMemo} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Alert, Button, Empty, Skeleton, Tag} from 'antd';
import {Link, useSearchParams} from 'react-router-dom';
import {ApiError, ChatApi} from '../../api';
import {MemoryEngineApi} from '../../api/memoryEngine';
import {HyMechanismsContractError, type HyCatalogItem, type HyIntegration, type HyMechanism} from '../../api/hyMechanisms';
import {useMemoryEngine, memoryEngineLabel} from '../../app/MemoryEngineProvider';
import {AppShell, ConsoleNav} from '../../components/AppShell';
import {PageHeader} from '../../components/PageHeader';
import {memoryTime} from './HyMemoryWorkspace';
import './hy-mechanisms.css';

const api=new MemoryEngineApi(new ChatApi());
const SOURCE='https://github.com/Tencent-Hunyuan/Hy-Memory/blob/2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed/';
const tabs=[{id:'path',title:'运行路径'},{id:'layers',title:'L0–L7 分层'},{id:'boundaries',title:'模式与能力边界'},{id:'evidence',title:'证据入口'}];
const integrations:Record<HyIntegration,{label:string;color?:string}>={configured:{label:'已接入',color:'cyan'},disabled:{label:'已关闭'},not_integrated:{label:'未接入'},reserved:{label:'保留层'},unknown:{label:'不可观测',color:'gold'}};
const groups:Record<string,string>={processing:'双系统处理',write:'写入与变化',storage:'存储',recall:'检索与注入',evolution:'演进与意图',routing:'场景路由',management:'平台管理',runtime:'运行与持久化'};
const stages=[{id:'source_trace',title:'平台原话',hint:'独立来源账本'},{id:'extraction',title:'写入与提取',hint:'模型协调，不保证每轮产出'},{id:'version_chain',title:'冲突与版本',hint:'保留演化关系'},{id:'vector_store',title:'持久存储',hint:'与平台原话分离'},{id:'normal_recall',title:'检索',hint:'按当前范围返回'},{id:'answer_injection',title:'上下文注入',hint:'返回证据不等于答案采用'}];

function Integration({value}:{value:HyIntegration}) {return <Tag color={integrations[value].color}>{integrations[value].label}</Tag>;}
function CodeEvidence({item}:{item:HyCatalogItem}) {return <details className="mechanism-code"><summary>查看代码依据</summary><p>以下是公开相对路径，不是现场健康探针。</p><ul>{item.evidence.map(path=><li key={path}><code>{path}</code></li>)}</ul></details>;}

/** 后端入口模板只映射至已实现页面；不插入虚假的 ID，也不自动调用证据接口。 */
function EvidenceLinks({item}:{item:HyMechanism}) {
  const links=new Map<string,{to:string;label:string}>();
  for(const endpoint of item.endpoints) {
    if(endpoint==='/api/memory-engine/items'||endpoint==='/api/memory-engine/items/{item_id}')links.set('items',{to:'/memories?view=items',label:'浏览活动条目并选择详情'});
    if(endpoint==='/api/memory-engine/sources/{event_id}')links.set('sources',{to:'/memories?view=items',label:'从条目选择单条平台来源'});
    if(endpoint==='/api/memory-engine/hy/operations')links.set('audit',{to:'/memories?view=activity',label:'查看平台管理操作记录'});
    if(endpoint==='/api/memory-engine/hy/profile')links.set('profile',{to:'/memories?view=profile',label:'核对基本画像读取能力'});
    if(endpoint==='/api/memory-engine/hy/workspace')links.set('management',{to:'/memories?view=status',label:'核对当前管理权限与处理状态'});
  }
  return <div className="mechanism-evidence-links">{Array.from(links.values()).map(link=><Link key={link.to+link.label} to={link.to}>{link.label}</Link>)}
    {!links.size&&<p>当前没有直接可浏览的执行证据接口；本页不现场调用模型或搜索生成轨迹。</p>}
    {item.id==='sdk_history'&&<p>SDK 历史开关与平台管理审计不同。当前关闭时不能用空历史推断没有发生变化。</p>}
  </div>;
}
function MechanismDetail({item}:{item:HyMechanism}) {
  return <section className="mechanism-detail" aria-labelledby="mechanism-detail-heading">
    <div className="mechanism-detail-heading"><Integration value={item.integration}/><span>{item.sdk_support==='platform'?'平台提供':item.sdk_support==='reserved'?'SDK 保留':'SDK 有实现'}</span></div>
    <h2 id="mechanism-detail-heading">{item.title}</h2><p className="mechanism-description">{item.description}</p>
    <h3>可以核对的证据</h3><EvidenceLinks item={item}/>
    <p className="mechanism-limit">“已接入”是代码装配声明，不等于本次成功执行、有数据、最近健康或质量通过。</p>
    <CodeEvidence item={item}/>
  </section>;
}

function readFailure(error:unknown) {
  if(error instanceof HyMechanismsContractError)return error.message;
  if(error instanceof ApiError) {
    if(error.code==='hy_mechanisms_busy')return '聊天或管理正在处理，引擎暂忙。这次没有取得新快照；请稍后手动刷新。';
    if(error.status===501)return '当前服务尚未提供 Hy 机制目录，或当前引擎不是 Hy。没有回落到旧库。';
    if(error.status===401)return '本机会话已不可用，请重新连接后核对。';
  }
  return '机制声明读取失败。未将缺失数据当作已关闭、零条目或正常运行。';
}

export function HyMechanismsWorkspace() {
  const engine=useMemoryEngine();
  const [params,setParams]=useSearchParams();
  const requested=params.get('mechanism_tab');
  const tab=tabs.some(item=>item.id===requested)?requested!:'path';
  const query=useQuery({queryKey:['hy-mechanisms-catalog'],queryFn:()=>api.mechanisms(),retry:false,staleTime:30000,
    refetchOnWindowFocus:false,enabled:engine.phase==='ready'&&engine.kind==='hy'});
  const data=engine.kind==='hy'?query.data:undefined;
  const mechanisms=data?.mechanisms??[];
  const selected=mechanisms.find(item=>item.id===params.get('mechanism'))??mechanisms.find(item=>item.id==='extraction')??mechanisms[0];
  const layers=useMemo(()=>[...(data?.layers??[])].sort((a,b)=>a.number-b.number),[data?.layers]);
  const layer=layers.find(item=>item.id===params.get('layer'))??layers[0];
  const grouped=useMemo(()=>{const map=new Map<string,HyMechanism[]>();for(const item of mechanisms)map.set(item.group,[...(map.get(item.group)??[]),item]);return Array.from(map);},[mechanisms]);
  function choose(values:Record<string,string>) {setParams(previous=>{const next=new URLSearchParams(previous);next.set('view','mechanisms');for(const [key,value] of Object.entries(values))next.set(key,value);return next;},{preventScrollReset:true});}
  const current=data&&!query.isError&&engine.phase==='ready';
  const selectedMissing=Boolean(params.get('mechanism'))&&!mechanisms.some(item=>item.id===params.get('mechanism'));

  return <AppShell subtitle="理解记忆怎样形成与使用" className="hy-mechanisms-shell" sidebar={<ConsoleNav active="mechanisms" legacyPath="/memories-legacy"/>}>
    <PageHeader eyebrow="长期记忆" title="记忆机制" description="从一段原话到一次回答，区分固定版支持、当前接入和真正可得的证据。"
      action={<Button disabled={query.isFetching||engine.refreshing} onClick={()=>engine.phase!=='ready'?engine.refresh():void query.refetch()}>刷新声明</Button>}/>
    {engine.phase!=='ready'&&<Alert showIcon type={engine.phase==='error'?'error':'info'} title={engine.phase==='error'?'当前引擎身份尚未确认':'正在确认当前引擎'} description="其他功能可继续使用；确认前不加载旧引擎数据。"/>}
    {engine.phase==='ready'&&engine.kind!=='hy'&&<Empty description={`${memoryEngineLabel(engine)}，当前未选择 Hy`}><Link to="/memories">进入当前记忆管理</Link><p>本页不会为查看机制而切换引擎、模式或资源。</p></Empty>}
    {query.isError&&<Alert showIcon type="warning" title={data?'未取得新声明，以下保留上次快照':'暂时无法读取机制声明'} description={<>{readFailure(query.error)}{data&&<p>上次快照：{memoryTime(data.observed_at)}。以下状态不是本次实时确认。</p>}</>}/>}
    {engine.phase==='ready'&&engine.kind==='hy'&&!data&&query.isFetching&&<div role="status" aria-label="正在读取机制声明"><Skeleton active paragraph={{rows:7}}/></div>}
    {data&&<>
      <section className="mechanism-snapshot" aria-label="机制声明范围"><div><strong>{current?'本次装配声明':'上次装配声明'}</strong><span>{memoryTime(data.observed_at)}</span></div><p>固定 SDK {data.sdk.version}；{data.mode??'模式未知'} / {data.scene??'场景未知'}。{data.assembly==='standard_worker'?'标准 worker 装配':'自定义或未知装配'}。</p><p>写入{data.runtime.write_enabled?'开启':'暂停'}，回答使用{data.runtime.use_enabled?'开启':'暂停'}；初始化标记{data.runtime.engine_initialized?'已设置':'未设置'}，worker 健康不可观测。</p><small>这里只读装配声明和内存开关，不扫描库、不计数、不执行检索，不代表最近成功时间。</small></section>
      <nav className="mechanism-tabs" aria-label="机制探索视图">{tabs.map(item=><button type="button" key={item.id} aria-current={tab===item.id?'page':undefined} onClick={()=>choose({mechanism_tab:item.id})}>{item.title}</button>)}</nav>
      {tab==='path'&&<>
        <section className="mechanism-path" aria-label="从原话到回答的常见路径">{stages.map((stage,index)=><button key={stage.id} type="button" disabled={!mechanisms.some(item=>item.id===stage.id)} aria-pressed={selected?.id===stage.id} onClick={()=>choose({mechanism:stage.id})}><span>{index+1}</span><strong>{stage.title}</strong><small>{stage.hint}</small></button>)}</section>
        <p className="mechanism-caption">这是常见路径，不表示一次请求已经逐步成功。下方完整目录包含接口返回的全部 {mechanisms.length} 项机制。</p>
        {selectedMissing&&<Alert type="info" title="链接选择的机制不在当前目录，先显示可用条目"/>}
        {!mechanisms.length?<Empty description="接口没有提供机制条目；这不表示记忆库为空"/>:<div className="mechanism-workspace">
          <div className="mechanism-mobile-picker"><label htmlFor="mechanism-select">选择全部机制</label><select id="mechanism-select" value={selected?.id??''} onChange={event=>choose({mechanism:event.target.value})}>{grouped.map(([group,items])=><optgroup key={group} label={groups[group]??group}>{items.map(item=><option key={item.id} value={item.id}>{item.title}（{integrations[item.integration].label}）</option>)}</optgroup>)}</select></div>
          <nav className="mechanism-picker" aria-label="完整机制目录">{grouped.map(([group,items])=><section key={group}><h2>{groups[group]??group}</h2>{items.map(item=><button key={item.id} type="button" aria-pressed={selected?.id===item.id} onClick={()=>choose({mechanism:item.id})}><span>{item.title}</span><small>{integrations[item.integration].label}</small></button>)}</section>)}</nav>
          {selected&&<MechanismDetail item={selected}/>}</div>}
      </>}
      {tab==='layers'&&<section aria-label="Hy 原生记忆分层"><Alert type="info" showIcon title="平台原话不等于 Hy L0" description="Hy L0 是基本信息聚合，L1 才是 SDK 原始记忆。平台来源账本独立保存用户/助手原话和处理状态。"/>
        <div className="hy-layer-map">{layers.map(item=><button type="button" key={item.id} aria-pressed={layer?.id===item.id} onClick={()=>choose({layer:item.id})}><strong>Hy L{item.number}</strong><span>{item.title}</span><small>{integrations[item.integration].label}</small></button>)}</div>
        {!layer?<Empty description="接口未提供层级目录，不推断为空库"/>:<section className="mechanism-detail layer-detail" aria-labelledby="layer-heading"><Integration value={layer.integration}/><h2 id="layer-heading">Hy L{layer.number}：{layer.title}</h2><p className="mechanism-description">{layer.description}</p><p>条目数量：未知。该声明接口不扫描或计数，不能用 0 代替未知。</p>
          {layer.number===0?<Link to="/memories?view=profile">核对基本画像与范围能力</Link>:layer.number===1?<p>SDK RAW 独立浏览尚未接入。可从已有条目回看可得的平台来源，不能把两者视为同一份原文。</p>:<Link to="/memories?view=items">浏览全部活动条目</Link>}
          <p className="mechanism-limit">列表没有全库按层筛选；浏览活动条目后只能筛选已加载的本页。保留层和关闭层不因为没有可见条目而变为零。</p><CodeEvidence item={layer}/></section>}
      </section>}
      {tab==='boundaries'&&<section aria-labelledby="modes-heading"><h2 id="modes-heading">模式与场景</h2><p className="mechanism-caption">以下差异属于锁定 SDK；选中标记来自装配声明。本页没有模式切换或启用按钮。</p><div className="mechanism-modes">{data.modes.map(mode=><article key={mode.id}><h3>{mode.title} {mode.selected===true&&<Tag color="cyan">当前装配</Tag>}</h3><p>{mode.description}</p>{mode.selected===null&&<small>当前选择未观测</small>}</article>)}</div><h2>全部机制的接入边界</h2><div className="mechanism-boundaries">{mechanisms.map(item=><article key={item.id}><div><h3>{item.title}</h3><Integration value={item.integration}/></div><p>{item.description}</p><button type="button" onClick={()=>choose({mechanism_tab:'path',mechanism:item.id})}>查看机制与证据</button></article>)}</div></section>}
      {tab==='evidence'&&<section aria-labelledby="evidence-heading"><h2 id="evidence-heading">从哪里核对事实</h2><div className="mechanism-evidence-table">
        <article><h3>真实活动条目与平台原话</h3><p>有界分页；选择条目后读取单条来源。不是原话全量导出，也不是按层完整统计。</p><Link to="/memories?view=items">选择条目核对来源</Link></article>
        <article><h3>基本画像</h3><p>聚合内容与真实管理能力分别读取；未知范围时不会伪装可用。</p><Link to="/memories?view=profile">查看画像读取能力</Link></article>
        <article><h3>平台管理审计</h3><p>用户纠正/删除的已完成、运行或不确定记录。与 SDK history 分开。</p><Link to="/memories?view=activity">查看管理记录</Link></article>
        <article><h3>本次处理与运行开关</h3><p>来源保存、派生结果和回答使用分别核对。状态未知不会显示成功。</p><Link to="/memories?view=status">查看处理状态</Link></article>
        <article><h3>已记录的网页轮次字段</h3><p>选择已有对话，展开“记忆证据”。平台保存的召回字段不等于完整 SDK trace、最终注入或模型实际采用；当前没有逐次最终注入证据接口。</p><Link to="/chat-react">到聊天中选择已有轮次</Link></article>
      </div><h2>当前证据缺口</h2>{data.evidence_gaps.length?<ul className="mechanism-gaps">{data.evidence_gaps.map(gap=><li key={gap}>{gap}</li>)}</ul>:<p>接口没有列出证据缺口；这不构成完整可观测性的证明。</p>}</section>}
      <footer className="mechanism-reference"><a href={`${SOURCE}README.md`} target="_blank" rel="noreferrer">固定 2.0.3 来源说明</a><p>本页不启用关闭功能，也不把版本目录当作本次运行成功记录。</p></footer>
    </>}
  </AppShell>;
}
