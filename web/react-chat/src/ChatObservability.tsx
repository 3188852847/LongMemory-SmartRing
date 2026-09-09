import {Tag} from 'antd';
import {Link} from 'react-router-dom';
import type {Config, DeviceStatus, Turn} from './api';

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
    <div className={`rail-cell tone-${deviceTone}`}><span className="rail-dot" aria-hidden="true"/><span><small>圆屏</small><strong>{deviceValue}</strong><em>{device?.connection_count ?? 0} 个连接</em></span></div>
    <div className={`rail-cell tone-${config?.enabled ? 'good' : 'warning'}`}><span className="rail-dot" aria-hidden="true"/><span><small>记忆服务</small><strong>{config?.enabled ? '已装配' : '未启用'}</strong><em>{activeMemoryCount === undefined ? 'L1 数量未知' : `${activeMemoryCount} 条有效 L1`}</em></span></div>
    <div className={`rail-cell tone-${model.tone}`}><span className="rail-dot" aria-hidden="true"/><span><small>回答模型</small><strong title={model.value}>{model.value}</strong><em>{model.detail}</em></span></div>
    <div className="rail-cell tone-idle"><span className="rail-dot" aria-hidden="true"/><span><small>召回策略</small><strong>{retrieval}</strong><em>{config?.method ?? '未装配'}</em></span></div>
  </section>;
}

function operationLabel(operation:string) {
  if (operation === 'add') return '新增';
  if (operation === 'noop') return '重复证据';
  if (operation === 'supersede') return '取代';
  if (operation === 'delete') return '删除';
  return operation;
}

export function memoryTraceSummary(turn?:Turn) {
  if (!turn) return {kind:'waiting', code:'WAITING', text:'发送消息后显示本轮记忆过程'};
  const l1 = turn.retrieved?.length ?? 0;
  const l2 = turn.scenario_retrieved?.length ?? 0;
  const l3 = turn.persona_retrieved?.length ?? 0;
  const writeCount = turn.writes?.length ?? 0;
  if (turn.memory_processing === 'source_only') return {kind:'warning', code:'SOURCE ONLY', text:'L0 已保存，L1 处理没有完成'};
  if (l1 + l2 + l3 > 0) return {kind:'hit', code:'MEM HIT', text:`回答使用 L1 ${l1} · L2 ${l2} · L3 ${l3}`};
  if (writeCount > 0) return {kind:'write', code:'MEM WRITE', text:`本轮产生 ${writeCount} 个记忆操作，但回答未召回旧记忆`};
  return {kind:'miss', code:'NO RECALL', text:'本轮没有召回长期记忆；不等于用户从未说过'};
}

/** 把调试 JSON 中最重要的记忆事实提升为人能直接阅读的证据面板。 */
export function TurnMemoryEvidence({turn}: {turn?:Turn}) {
  const summary = memoryTraceSummary(turn);
  return <section className={`turn-evidence trace-${summary.kind}`} aria-label="本轮记忆证据">
    <header><span>[ {summary.code} ]</span><p>{summary.text}</p></header>
    {!turn ? <p className="trace-empty">这里会显示回答实际使用的 L1、L2、L3 和本轮写入，而不是模型声称自己记住了什么。</p> : <>
      {Boolean(turn.retrieved?.length) && <div className="trace-group"><h3>L1 原子记忆</h3>{turn.retrieved!.map(item => <article key={item.item_id}><p>{item.content}</p><code>{item.item_id}</code><footer><small>{item.source_event_ids?.length ?? 0} 条 L0 来源</small><Link className="trace-source-link" to={`/memories?memory_id=${encodeURIComponent(item.item_id)}`}>核对 L0 原话</Link></footer></article>)}</div>}
      {Boolean(turn.scenario_retrieved?.length) && <div className="trace-group"><h3>L2 生活场景</h3>{turn.scenario_retrieved!.map(item => <article key={item.scenario_id}><strong>{item.title}</strong><p>{item.summary}</p><code>{item.scenario_id}</code><footer><small>{item.source_memory_ids.length} 条 L1 来源</small><Link className="trace-source-link" to={`/scenarios?scenario_id=${encodeURIComponent(item.scenario_id)}`}>核对场景依据</Link></footer></article>)}</div>}
      {Boolean(turn.persona_retrieved?.length) && <div className="trace-group"><h3>L3 用户画像</h3>{turn.persona_retrieved!.map(item => <article key={item.persona_id}><strong>{item.label}</strong><p>{item.statement}</p><code>{item.persona_id}</code><footer><small>已接受画像</small><Link className="trace-source-link" to={`/personas?persona_id=${encodeURIComponent(item.persona_id)}`}>核对画像依据</Link></footer></article>)}</div>}
      {Boolean(turn.writes?.length) && <div className="trace-group"><h3>本轮记忆写入</h3><p className="trace-tags">{turn.writes!.map((item, index) => <Tag key={`${item.item_id ?? index}-${item.operation}`}>{operationLabel(item.operation)}</Tag>)}</p></div>}
      <details><summary>查看完整运行过程</summary><pre>{JSON.stringify(turn, null, 2)}</pre></details>
    </>}
  </section>;
}
