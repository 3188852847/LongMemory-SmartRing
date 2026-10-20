import type {HyLayerPage} from '../../api/hyLayerData';
import {memoryTime} from './HyMemoryWorkspace';
import {hyCapabilityView,type HyCapabilityView,type HyCapabilityState,type HyRuntimeGateSnapshot} from './hyCapabilityView';

const labels:Record<HyCapabilityState,string>={configured:'已配置',enabled:'已启用',disabled:'未启用',unknown:'未知',unsupported:'不支持',failed:'失败',partial:'部分覆盖',empty:'无条目',present:'有已保存内容',idle:'空闲',running:'运行中',blocked:'受限'};
const axes=[['expected','期望配置'],['instance','实例实际能力'],['coverage','证据与条目覆盖'],['background','后台任务'],['management','管理可用性']] as const;

/** 受控、只读；不采样、不轮询、不启用机制，也不把未知证据投影成成功。 */
export function HyLayerStatus({page,capabilities,runtimeSnapshot}:{page:HyLayerPage;capabilities?:HyCapabilityView;runtimeSnapshot?:HyRuntimeGateSnapshot}) {
  if(!['l6_schema','l7_intention'].includes(page.layer))return null;
  const view=capabilities??hyCapabilityView(page);
  return <details className="hy-layer-capability" aria-label="分层接入与运行证据">
    <summary>接入与运行证据 <span>配置：{labels[view.expected.state]}；内容：{labels[view.coverage.state]}</span></summary>
    <dl>{axes.map(([axis,title])=><div key={axis}><dt>{title}</dt><dd><strong>{labels[view[axis].state]}</strong><p>{view[axis].description}</p><small>{view[axis].observed_at?`证据读取于 ${memoryTime(view[axis].observed_at)}`:'该项证据时间未提供'}</small></dd></div>)}</dl>
    <p>{runtimeSnapshot?<>{runtimeSnapshot.stale?'上次':'本次'}运行开关快照：写入{runtimeSnapshot.runtime.write_enabled?'开启':'暂停'}，回答使用{runtimeSnapshot.runtime.use_enabled?'开启':'暂停'}；读取于 {memoryTime(runtimeSnapshot.observed_at)}。</>:'运行开关快照尚未提供。'} 开关开启不等于 L6/L7 生成、管理或注入已成功。</p>
    <p>原生最后更新时间尚未提供；存储时间、有效期和本页读取时间分别核对。</p>
  </details>;
}
