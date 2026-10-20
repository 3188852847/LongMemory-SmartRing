import type {HyLayerPage} from '../../api/hyLayerData';
import type {HyMechanismsSnapshot} from '../../api/hyMechanisms';

/** 页面内投影，不是新的 HTTP/SDK 协议；AB 的能力 DTO 在边界确认后适配到这里。 */
export type HyCapabilityState='configured'|'enabled'|'disabled'|'unknown'|'unsupported'|'failed'|'partial'|'empty'|'present'|'idle'|'running'|'blocked';
export interface HyCapabilityFact {state:HyCapabilityState;description:string;observed_at:string|null}
export interface HyCapabilityView {
  expected:HyCapabilityFact;instance:HyCapabilityFact;coverage:HyCapabilityFact;
  background:HyCapabilityFact;management:HyCapabilityFact;
}
export interface HyRuntimeGateSnapshot {
  runtime:Pick<HyMechanismsSnapshot['runtime'],'write_enabled'|'use_enabled'>;
  observed_at:string;stale:boolean;
}

/** 旧端点没有实例/任务/管理证明，只能投影已明确返回的声明与读覆盖。 */
export function hyCapabilityView(page:HyLayerPage):HyCapabilityView {
  const observed_at=page.observed_at;
  const expected:HyCapabilityFact={state:page.generation_state==='configured'?'configured':page.generation_state==='disabled'?'disabled':'unknown',
    description:page.generation_state==='configured'?'生成配置已接入；尚不能证明本实例执行过生成。':page.generation_state==='disabled'?'返回的生成声明为关闭；历史内容仍可能存在。':'生成配置尚不能确认。',observed_at};
  const unavailable=()=>({state:'unknown' as const,description:'当前逐层端点未提供该项实例证据。',observed_at:null});
  return {expected,instance:unavailable(),background:unavailable(),management:{state:'unknown',description:'逐层只读成功不能证明纠正、删除或后台写入已获准。',observed_at:null},
    coverage:{state:page.read_status==='unavailable'?'blocked':page.coverage!=='vdb_complete'?'partial':page.data_state==='empty'?'empty':page.data_state==='present'?'present':'unknown',
      description:page.read_status==='unavailable'?'本次未取得可安全展示的内容。':page.coverage!=='vdb_complete'?'本次只读向量范围，图中内容与派生关系尚未确认。':page.data_state==='empty'?'所选读取范围内没有条目；不推断其他状态或页。':page.data_state==='present'?'已返回本页保存内容；不证明当前生成或后台任务已成功。':'当前读取范围的内容尚不能确认。',observed_at}};
}
