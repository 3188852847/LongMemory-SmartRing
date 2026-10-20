import {Tag} from 'antd';
import type {HyStoredRecord,HyRecordProvenance as Provenance} from '../../api/hyLayerData';

const statuses:Record<Provenance['status'],string>={verbatim_user:'用户原话',explicit_correction:'用户明确纠正',model_inference_unverified:'未证实模型推断'};
const basis:Record<Provenance['dependency_basis'],string>={explicit_correction:'用户明确纠正',scope_context_envelope:'潜在上下文依赖',legacy_unobserved:'历史来源未观测',verbatim_current_input:'当前输入原话核对',raw_exact_match:'与 RAW 原话精确匹配'};

/** 仅消费已返回的来源与许可，不从层名、ACTIVE、纠正或来源ID数量推断可信程度。 */
export function HyRecordProvenance({item,detail=false}:{item:HyStoredRecord;detail?:boolean}) {
  if(!['l2_fact','l3_summary','l4_identity'].includes(item.layer))return null;
  const p=item.provenance;
  return <section className="hy-record-provenance" aria-label="来源可信类型与注入许可">
    <div className="hy-layer-record-meta"><Tag>{p?statuses[p.status]:'来源可信类型未知'}</Tag><strong>{p?(p.injection_allowed?'当前允许注入':'当前禁止注入'):'注入许可未知'}</strong></div>
    {!p?<p>当前响应没有提供来源可信信息；完整性与注入许可均未知。</p>:p.status==='model_inference_unverified'?<p>模型归纳或推断的语义来源尚未证实完整。</p>:p.status==='explicit_correction'?<p>内容来源是用户明确纠正；标签只说明这条记录的来源。</p>:null}
    {detail&&<><dl><div><dt>语义来源完整性</dt><dd>{p?(p.semantic_source_complete?'已证实完整':'尚未证实完整'):'未知'}</dd></div><div><dt>依赖依据</dt><dd>{p?basis[p.dependency_basis]:'未知'}</dd></div></dl>
      {p?.dependency_basis==='scope_context_envelope'&&<p>记录的是潜在上下文依赖范围，不是模型真实引用或逐句归因。</p>}
      {p?.dependency_basis==='legacy_unobserved'&&<p>历史依赖没有被观测，不能解释为没有依赖。</p>}
      <p>注入许可是本次读取时后端的判断，不代表已用于某次回答，也不代表未来意图已执行。</p>
    </>}
  </section>;
}
