import type {HyCapabilityFact,HyCapabilityView} from '../../features/memory/hyCapabilityView';

/** 仅供受控组件验收的合成投影；不是 AB 原生 DTO，也不是个人图谱证据。 */
export function capabilityFixture(patch:Partial<HyCapabilityView>={}):HyCapabilityView {
  const fact=(state:HyCapabilityFact['state'],description:string):HyCapabilityFact=>({state,description:`合成验收：${description}`,observed_at:'2026-10-21T04:00:00Z'});
  return {expected:fact('configured','期望生成配置已接入'),instance:fact('enabled','实例能力证据已返回'),
    coverage:fact('partial','仅部分派生记录有可得来源'),background:fact('running','有受控后台任务'),management:fact('blocked','当前证明未允许管理'),...patch};
}
