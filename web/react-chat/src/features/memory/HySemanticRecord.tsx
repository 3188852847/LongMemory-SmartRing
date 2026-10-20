import {Tag} from 'antd';
import type {HyStoredRecord} from '../../api/hyLayerData';

const derivations={ready:'派生可用',isolated:'派生已隔离',stored:'已保存意图',expired:'意图已过期'};

/** 只展示原生派生证据；记忆 ID 不带层信息，不能伪造跨层详情链接或完整关系图。 */
export function HySemanticRecord({item,detail=false}:{item:HyStoredRecord;detail?:boolean}) {
  if(!item.semantic_kind)return null;
  return <section className="hy-semantic-record" aria-label="语义记忆与派生依据">
    <div className="hy-layer-record-meta"><Tag>{item.semantic_kind==='model_inference'?'模型归纳':'未来意图'}</Tag><strong>{item.derivation_state?derivations[item.derivation_state]:'派生状态未知'}</strong></div>
    {item.semantic_kind==='model_inference'?<p>{item.derivation_state==='isolated'?'当前派生已隔离，不用于当前回答；隔离不表示关闭生成或删除记录。':'图式是模型归纳，应沿依据核对，不能直接当作用户事实。'}</p>:
      <p>{item.derivation_state==='expired'?'有效期已过，不表示意图已经执行或完成。':'保存未来意图不表示已经执行或完成。'} 本条没有执行或主动联系授权。</p>}
    {detail&&<><h3>派生依据记忆 ID</h3>{item.evidence_memory_ids===null||item.evidence_memory_ids===undefined?<p>依据关联未知，不能解释为没有来源。</p>:item.evidence_memory_ids.length?<><ul>{item.evidence_memory_ids.map(id=><li key={id}><code>{id}</code></li>)}</ul><p>这里只显示最多16个可证明的依据 ID；平台原话在下方单独读取，不自动跨层补读。</p></>:<p>本条没有返回依据 ID；不推断完整派生历史。</p>}</>}
  </section>;
}
