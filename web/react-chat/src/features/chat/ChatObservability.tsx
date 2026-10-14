import {Button, Space, Tag} from 'antd';
import {Link} from 'react-router-dom';
import type {Config, DeviceStatus, MemoryFeedbackKind, Turn} from '../../api';

type RailProps = {
  config?:Config;
  device?:DeviceStatus;
  deviceFailed:boolean;
  activeMemoryCount?:number;
};

function modelState(config?:Config) {
  if (!config?.enabled) return {tone:'idle', value:'未启用', detail:'文字聊天'};
  if (config.provider === 'fake') return {tone:'idle', value:'Fake', detail:'离线工程替身'};
  if (config.model_health?.state === 'available') return {tone:'good', value:config.model, detail:'最近验证可用'};
  if (config.model_health?.state === 'unavailable') return {tone:'bad', value:config.model, detail:'最近验证失败'};
  return {tone:'warning', value:config.model, detail:'尚未验证'};
}

/** 顶部只呈现服务实际返回的状态；没有探测值时明确写“未知”，不猜测正常。 */
export function ConsoleStatusRail({config, device, deviceFailed, activeMemoryCount}:RailProps) {
  const model = modelState(config);
  const deviceTone = deviceFailed ? 'bad' : device?.ready ? 'good' : 'warning';
  const deviceValue = deviceFailed ? '状态未知' : device?.ready ? '已连接' : '等待圆屏';
  const retrieval = config?.retrieval === 'keyword_dense_rrf_v1' ? '关键词＋向量' : config?.retrieval ? '关键词' : '未装配';
  return <section className="console-status-rail" aria-label="当前系统状态">
    <Link aria-label="查看圆屏诊断" to="/device" className={`rail-cell tone-${deviceTone}`}><span className="rail-dot" aria-hidden="true"/><span><small>圆屏</small><strong>{deviceValue}</strong><em>{device?.connection_count ?? 0} 个连接</em></span></Link>
    <Link aria-label="查看记忆管理" to="/memories" className={`rail-cell tone-${config?.enabled ? 'good' : 'warning'}`}><span className="rail-dot" aria-hidden="true"/><span><small>记忆服务</small><strong>{config?.enabled ? '已装配' : '未启用'}</strong><em>{activeMemoryCount === undefined ? 'L1 数量未知' : `${activeMemoryCount} 条有效 L1`}</em></span></Link>
    <Link aria-label="查看模型诊断" to="/settings?tab=model" className={`rail-cell tone-${model.tone}`}><span className="rail-dot" aria-hidden="true"/><span><small>回答模型</small><strong title={model.value}>{model.value}</strong><em>{model.detail}</em></span></Link>
    <Link aria-label="查看记忆运行模式" to="/memories" className="rail-cell tone-idle"><span className="rail-dot" aria-hidden="true"/><span><small>召回策略</small><strong>{retrieval}</strong><em>{config?.method ?? '未装配'}</em></span></Link>
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

export function memoryTraceSummary(turn?:Turn) {
  if (!turn) return {kind:'waiting', code:'WAITING', text:'发送消息后显示本轮记忆过程'};
  const l1 = turn.retrieved?.length ?? 0;
  const l2 = turn.scenario_retrieved?.length ?? 0;
  const l3 = turn.persona_retrieved?.length ?? 0;
  const writeCount = turn.writes?.length ?? 0;
  if (turn.memory_processing === 'source_only') return {kind:'warning', code:'SOURCE ONLY', text:'L0 已保存，L1 处理没有完成'};
  if (l1 + l2 + l3 > 0) return {kind:'hit', code:'MEM HIT', text:`本轮召回 L1 ${l1} · L2 ${l2} · L3 ${l3}`};
  if (writeCount > 0) return {kind:'write', code:'MEM WRITE', text:`本轮产生 ${writeCount} 个记忆操作，但回答未召回旧记忆`};
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
    {turn.memory_feedback&&<p className="memory-feedback-diagnosis">{memoryFeedbackDiagnosis(turn)}</p>}
  </section>;
}

/** 只给排查入口，不把人工标签和可见轨迹推断成已确认根因。 */
export function memoryFeedbackDiagnosis(turn:Turn) {
  const kind = turn.memory_feedback?.kind;
  const recalled = (turn.retrieved?.length ?? 0) + (turn.scenario_retrieved?.length ?? 0) + (turn.persona_retrieved?.length ?? 0);
  if (kind === 'memory_ok') return '正常对照样本：保留当前轨迹，用于和失败样本比较。';
  if (kind === 'memory_irrelevant') return '不需要记忆的负例：先保留，不把它计作记忆故障。';
  if (kind === 'recall_miss') return recalled
    ? '已有记忆进入本轮轨迹：优先核对注入预算，以及回答是否采用了证据。'
    : '本轮没有召回 L1/L2/L3：优先核对检索查询和候选覆盖。';
  if (kind === 'wrong_memory') return recalled
    ? '本轮确实召回了长期记忆：优先核对内容、时效、主体和排序。'
    : '轨迹没有显示长期记忆：先核对短期上下文或回答模型，不要直接归因于记忆库。';
  return '尚未人工复核。';
}

/** 把调试 JSON 中最重要的记忆事实提升为人能直接阅读的证据面板。 */
export function TurnMemoryEvidence({turn}: {turn?:Turn}) {
  const summary = memoryTraceSummary(turn);
  return <section className={`turn-evidence trace-${summary.kind}`} aria-label="本轮记忆证据">
    <header><span>[ {summary.code} ]</span><p>{summary.text}</p></header>
    {!turn ? <p className="trace-empty">这里显示本轮召回的事实、场景、画像与写入；是否被答案采用仍需核对回答。</p> : <>
      {Boolean(turn.retrieved?.length) && <div className="trace-group"><h3>L1 原子记忆</h3>{turn.retrieved!.map(item => <article key={item.item_id}>{item.temporal_role==='historical'&&<p><Tag color="gold">历史事实</Tag>生效 {displayTime(item.valid_from)} · 结束 {displayTime(item.valid_to)}</p>}<p>{item.content}</p><code>{item.item_id}</code><footer><small>{item.source_event_ids?.length ?? 0} 条 L0 来源</small><Link className="trace-source-link" to={`/memories?memory_id=${encodeURIComponent(item.item_id)}`}>核对 L0 原话</Link></footer></article>)}</div>}
      {Boolean(turn.scenario_retrieved?.length) && <div className="trace-group"><h3>L2 生活场景</h3>{turn.scenario_retrieved!.map(item => <article key={item.scenario_id}><strong>{item.title}</strong><p>{item.summary}</p><code>{item.scenario_id}</code><footer><small>{item.source_memory_ids.length} 条 L1 来源</small><Link className="trace-source-link" to={`/scenarios?scenario_id=${encodeURIComponent(item.scenario_id)}`}>核对场景依据</Link></footer></article>)}</div>}
      {Boolean(turn.persona_retrieved?.length) && <div className="trace-group"><h3>L3 用户画像</h3>{turn.persona_retrieved!.map(item => <article key={item.persona_id}><strong>{item.label}</strong><p>{item.statement}</p><code>{item.persona_id}</code><footer><small>已接受画像</small><Link className="trace-source-link" to={`/personas?persona_id=${encodeURIComponent(item.persona_id)}`}>核对画像依据</Link></footer></article>)}</div>}
      {Boolean(turn.writes?.length) && <div className="trace-group"><h3>本轮记忆写入</h3><p className="trace-tags">{turn.writes!.map((item, index) => <Tag key={`${item.item_id ?? index}-${item.operation}`}>{operationLabel(item.operation)}</Tag>)}</p></div>}
      <details><summary>查看完整运行过程</summary><pre>{JSON.stringify(turn, null, 2)}</pre></details>
    </>}
  </section>;
}
