import {useMemoryEngine, memoryEngineLabel, retrievalLabel} from '../../app/MemoryEngineProvider';
import {Button, Space, Tag} from 'antd';
import {Link} from 'react-router-dom';
import type {Config, DeviceStatus, MemoryFeedbackKind, Turn} from '../../api';

type RailProps = {
  config?:Config;
  device?:DeviceStatus;
  deviceFailed:boolean;
  activeMemoryCount?:number;
  memoryCountState?:'loading'|'error'|'unavailable'|'ready';
};

function modelState(config?:Config) {
  if (!config?.enabled) return {tone:'idle', value:'未启用', detail:'文字聊天'};
  if (config.provider === 'fake') return {tone:'idle', value:'Fake', detail:'离线工程替身'};
  if (config.model_health?.state === 'available') return {tone:'good', value:config.model, detail:'最近验证可用'};
  if (config.model_health?.state === 'unavailable') return {tone:'bad', value:config.model, detail:'最近验证失败'};
  return {tone:'warning', value:config.model, detail:'尚未验证'};
}

/** 顶部只呈现服务实际返回的状态；没有探测值时明确写“未知”，不猜测正常。 */
export function ConsoleStatusRail({config, device, deviceFailed, activeMemoryCount,memoryCountState}:RailProps) {
  const engine=useMemoryEngine();
  const model = modelState(config);
  const deviceTone = deviceFailed ? 'bad' : device?.ready ? 'good' : 'warning';
  const deviceValue = deviceFailed ? '状态未知' : device?.ready ? '已连接' : '等待圆屏';
  const retrieval = retrievalLabel(config?.retrieval);
  return <section className="console-status-rail" aria-label="当前系统状态">
    <Link aria-label="查看圆屏诊断" to="/device" className={`rail-cell tone-${deviceTone}`}><span className="rail-dot" aria-hidden="true"/><span><small>圆屏</small><strong>{deviceValue}</strong><em>{device?.connection_count ?? 0} 个连接</em></span></Link>
    <Link aria-label="查看记忆管理" to="/memories" className={`rail-cell tone-${engine.phase==='error'?'warning':'idle'}`}><span className="rail-dot" aria-hidden="true"/><span><small>记忆引擎</small><strong>{memoryEngineLabel(engine)}</strong><em>{engine.phase!=='ready'?'当前身份尚未确认':activeMemoryCount!==undefined?`${activeMemoryCount} 条${engine.kind==='legacy'?'有效 L1':'活动条目'}`:memoryCountState==='error'?'条目数量读取失败':memoryCountState==='loading'?'正在读取条目数量':engine.kind==='hy'?'不在此页扫描条目数量':'条目数量尚未提供'}</em></span></Link>
    <Link aria-label="查看模型诊断" to="/settings?tab=model" className={`rail-cell tone-${model.tone}`}><span className="rail-dot" aria-hidden="true"/><span><small>回答模型</small><strong title={model.value}>{model.value}</strong><em>{model.detail}</em></span></Link>
    <Link aria-label="查看记忆运行模式" to={engine.kind==='hy'?'/memories?view=mechanisms':'/memories'} className="rail-cell tone-idle"><span className="rail-dot" aria-hidden="true"/><span><small>召回策略</small><strong>{retrieval}</strong><em>{config?.method ?? '未装配'}</em></span></Link>
  </section>;
}

function operationLabel(operation:string) {
  if (operation === 'add') return '新增';
  if (operation === 'noop') return '重复证据';
  if (operation === 'supersede') return '取代';
  if (operation === 'delete') return '删除';
  return operation;
}

function displayTime(value?:string|null) {
  if (!value) return '未记录';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '时间格式异常' : parsed.toLocaleString('zh-CN');
}

export function memoryTraceSummary(turn?:Turn,representation:'legacy'|'neutral'='legacy') {
  if (!turn) return {kind:'waiting', code:'WAITING', text:'发送消息后显示本轮记忆过程'};
  const l1 = turn.retrieved?.length ?? 0;
  const l2 = turn.scenario_retrieved?.length ?? 0;
  const l3 = turn.persona_retrieved?.length ?? 0;
  const writeCount = turn.writes?.length ?? 0;
  if (turn.memory_processing === 'source_only') return {kind:'warning', code:'SOURCE ONLY', text:representation==='legacy'?'L0 已保存，L1 处理没有完成':'平台原话已保存，引擎派生没有完成'};
  if (l1 + l2 + l3 > 0) return {kind:'hit', code:'MEM HIT', text:representation==='legacy'?`本轮召回 L1 ${l1} · L2 ${l2} · L3 ${l3}`:`本轮返回 ${l1+l2+l3} 条记忆证据，不能据此证明最终注入或回答采用`};
  if (writeCount > 0) return {kind:'write', code:'MEM WRITE', text:representation==='legacy'?`本轮产生 ${writeCount} 个记忆操作，但回答未召回旧记忆`:`本轮记录 ${writeCount} 个记忆操作，未见已记录的召回条目`};
  if(representation==='neutral'&&!Array.isArray(turn.retrieved))return {kind:'warning',code:'TRACE UNKNOWN',text:'本轮未提供可核对的召回字段，不能按零召回解释'};
  if(representation==='neutral')return {kind:'miss',code:'NO RECALL',text:'本轮保存的召回列表为空；不能据此证明 SDK 未执行或用户从未说过'};
  return {kind:'miss', code:'NO RECALL', text:'本轮没有召回长期记忆；不等于用户从未说过'};
}

const feedbackOptions:Array<{kind:MemoryFeedbackKind;label:string}> = [
  {kind:'memory_ok',label:'记忆使用正常'},
  {kind:'recall_miss',label:'没想起已有记忆'},
  {kind:'wrong_memory',label:'使用了错误记忆'},
  {kind:'memory_irrelevant',label:'回答与记忆无关'},
];

/** 这是所有者的内部质量标注，不把评价混入 L0–L3，也不触发自动重答。 */
export function MemoryFeedbackControls({turn,disabled,onSelect}:{
  turn:Turn;disabled:boolean;onSelect:(kind:MemoryFeedbackKind)=>void;
}) {
  const engine=useMemoryEngine();
  if (turn.status !== 'completed' || !turn.answer || !turn.request_id) return null;
  return <section className="memory-feedback-controls" aria-label="标记本轮记忆表现">
    <small>这轮记忆表现</small>
    <Space size={[6,6]} wrap>{feedbackOptions.map(option => <Button
      key={option.kind} size="small" disabled={disabled}
      type={turn.memory_feedback?.kind === option.kind ? 'primary' : 'default'}
      aria-pressed={turn.memory_feedback?.kind === option.kind}
      onClick={() => onSelect(option.kind)}
    >{option.label}</Button>)}</Space>
    <em>{turn.memory_feedback ? `已复核 · 修订 ${turn.memory_feedback.revision}` : '仅记录标记，不会重答或修改记忆'}</em>
    {turn.memory_feedback&&<p className="memory-feedback-diagnosis">{memoryFeedbackDiagnosis(turn,engine.kind==='legacy'?'legacy':'neutral')}</p>}
  </section>;
}

/** 只给排查入口，不把人工标签和可见轨迹推断成已确认根因。 */
export function memoryFeedbackDiagnosis(turn:Turn,representation:'legacy'|'neutral'='legacy') {
  const kind = turn.memory_feedback?.kind;
  const recalled = (turn.retrieved?.length ?? 0) + (turn.scenario_retrieved?.length ?? 0) + (turn.persona_retrieved?.length ?? 0);
  if (kind === 'memory_ok') return '正常对照样本：保留当前轨迹，用于和失败样本比较。';
  if (kind === 'memory_irrelevant') return '不需要记忆的负例：先保留，不把它计作记忆故障。';
  if (kind === 'recall_miss') return recalled
    ? '已有记忆进入本轮轨迹：优先核对注入预算，以及回答是否采用了证据。'
    : representation==='legacy'?'本轮没有召回 L1/L2/L3：优先核对检索查询和候选覆盖。':'本轮没有记录召回条目：优先核对已保存的查询与候选覆盖；缺失轨迹不能证明 SDK 未执行。';
  if (kind === 'wrong_memory') return recalled
    ? '本轮确实召回了长期记忆：优先核对内容、时效、主体和排序。'
    : '轨迹没有显示长期记忆：先核对短期上下文或回答模型，不要直接归因于记忆库。';
  return '尚未人工复核。';
}

/** 把调试 JSON 中最重要的记忆事实提升为人能直接阅读的证据面板。 */
export function TurnMemoryEvidence({turn}: {turn?:Turn}) {
  const engine=useMemoryEngine();
  const legacy=engine.kind==='legacy';
  const summary = memoryTraceSummary(turn,legacy?'legacy':'neutral');
  return <section className={`turn-evidence trace-${summary.kind}`} aria-label="本轮记忆证据">
    <header><span>[ {summary.code} ]</span><p>{summary.text}</p></header>
    {!turn ? <p className="trace-empty">这里显示本轮已记录的记忆证据；逐项写入或最终注入未提供时保持未知，是否被答案采用仍需核对回答。</p> : <>
      {Boolean(turn.retrieved?.length) && <div className="trace-group"><h3>{legacy?'L1 原子记忆':'召回记忆条目'}</h3>{turn.retrieved!.map(item => <article key={item.item_id}>{item.temporal_role==='historical'&&<p><Tag color="gold">历史事实</Tag>生效 {displayTime(item.valid_from)} · 结束 {displayTime(item.valid_to)}</p>}<p>{item.content}</p><code>{item.item_id}</code><footer><small>{item.source_event_ids===null||item.source_event_ids===undefined?'来源关联未提供':`${item.source_event_ids.length} 条${legacy?' L0':'平台'}来源`}</small><Link className="trace-source-link" to={`/memories?${legacy?'memory_id':'item'}=${encodeURIComponent(item.item_id)}`}>{legacy?'核对 L0 原话':'核对条目与平台来源'}</Link></footer></article>)}</div>}
      {Boolean(turn.scenario_retrieved?.length) && <div className="trace-group"><h3>{legacy?'L2 生活场景':'旧格式场景补充'}</h3>{turn.scenario_retrieved!.map(item => <article key={item.scenario_id}><strong>{item.title}</strong><p>{item.summary}</p><code>{item.scenario_id}</code><footer><small>{item.source_memory_ids.length} 条 L1 来源</small><Link className="trace-source-link" to={`/scenarios?scenario_id=${encodeURIComponent(item.scenario_id)}`}>核对场景依据</Link></footer></article>)}</div>}
      {Boolean(turn.persona_retrieved?.length) && <div className="trace-group"><h3>{legacy?'L3 用户画像':'旧格式画像补充'}</h3>{turn.persona_retrieved!.map(item => <article key={item.persona_id}><strong>{item.label}</strong><p>{item.statement}</p><code>{item.persona_id}</code><footer><small>已接受画像</small><Link className="trace-source-link" to={`/personas?persona_id=${encodeURIComponent(item.persona_id)}`}>核对画像依据</Link></footer></article>)}</div>}
      {Boolean(turn.writes?.length) && <div className="trace-group"><h3>本轮记忆写入</h3><p className="trace-tags">{turn.writes!.map((item, index) => <Tag key={`${item.item_id ?? index}-${item.operation}`}>{operationLabel(item.operation)}</Tag>)}</p></div>}
      <p className="subtle">这里是平台保存的轮次字段，不是 SDK 内部决策日志或完整最终提示；缺失字段不代表对应机制没有发生。</p><details><summary>查看已记录的运行字段</summary><pre>{JSON.stringify(turn, null, 2)}</pre></details>
    </>}
  </section>;
}
