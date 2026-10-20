/** Hy 2.0.3 专属逐层只读协议；配置、读取范围和实际内容互不替代。 */
export const HY_LAYERS=['l0_basic_info','l1_raw','l2_fact','l3_summary','l4_identity','l5_knowledge','l6_schema','l7_intention'] as const;
export type HyLayerId=typeof HY_LAYERS[number];
export const HY_LAYER_STATES=['all','active','superseded','negated','conflicted','shadow','archived'] as const;
export type HyLayerState=typeof HY_LAYER_STATES[number];
export interface HyStoredRecord {
  item_id:string; native_id:string; kind:'stored_record'|'aggregate_profile'; layer:HyLayerId;
  content:string; content_chars:number; content_truncated:boolean; status:string|null; is_latest:boolean|null;
  recorded_at:string|null; memory_at:string|null; valid_from:string|null; valid_until:string|null;
  supersedes:string[]; superseded_by:string[]; version_links_limited:boolean;
  source_event_ids:string[]|null; source_raw_memory_id:string|null;
  basic_info?:Record<string,string|number|boolean|null>;
  field_sources?:Record<string,{native_id:string|null;source_event_ids:string[]|null}>;
  stored_version_count?:number;
}
export interface HyLayerRead {
  schema_version:1;layer:HyLayerId;sdk_support:'implemented'|'historical'|'reserved';
  generation_state:'configured'|'disabled'|'historical'|'reserved'|'unknown';
  read_status:'readable'|'partial'|'unavailable';data_state:'present'|'empty'|'unknown';
  coverage:'vdb_complete'|'vdb_only_graph_unopened'|'unavailable';reason_code:string|null;observed_at:string;
}
export interface HyLayerPage extends HyLayerRead {
  items:HyStoredRecord[];limit:number;offset:number;state:HyLayerState;
  has_more:boolean|null;total:number|null;count_scope:'aggregate_profile'|'owner_agent_source_layer_state_vdb';
}
export interface HyLayerDetail extends HyLayerRead {item:HyStoredRecord|null;versions:HyStoredRecord[]|null}
export class HyLayerContractError extends Error {}
const object=(v:unknown):v is Record<string,unknown>=>Boolean(v)&&typeof v==='object'&&!Array.isArray(v);
const oneOf=(v:unknown,values:readonly unknown[])=>values.includes(v);
const integer=(v:unknown,min=0,max=Number.MAX_SAFE_INTEGER):v is number=>Number.isSafeInteger(v)&&Number(v)>=min&&Number(v)<=max;
export const hyLayerIdentifier=(v:unknown):v is string=>typeof v==='string'&&Boolean(v.trim())&&v.length<=256&&!/[\u0000-\u001f\u007f/\\]/.test(v)&&v!=='.'&&v!=='..';
const ids=(v:unknown):v is string[]=>Array.isArray(v)&&v.length<=128&&v.every(hyLayerIdentifier);
const time=(v:unknown)=>v===null||(typeof v==='string'&&!Number.isNaN(Date.parse(v)));
function record(v:unknown,layer:HyLayerId):boolean {
  if(!object(v)||!hyLayerIdentifier(v.item_id)||!hyLayerIdentifier(v.native_id)||v.layer!==layer||
    !oneOf(v.kind,['stored_record','aggregate_profile'])||typeof v.content!=='string'||!integer(v.content_chars)||
    typeof v.content_truncated!=='boolean'||!(v.status===null||typeof v.status==='string')||
    !(v.is_latest===null||typeof v.is_latest==='boolean')||!['recorded_at','memory_at','valid_from','valid_until'].every(k=>time(v[k]))||
    !ids(v.supersedes)||!ids(v.superseded_by)||typeof v.version_links_limited!=='boolean'||
    !(v.source_event_ids===null||ids(v.source_event_ids))||!(v.source_raw_memory_id===null||hyLayerIdentifier(v.source_raw_memory_id)))return false;
  if(v.kind==='aggregate_profile')return layer==='l0_basic_info'&&v.item_id==='profile'&&integer(v.stored_version_count,1,128)&&
    object(v.basic_info)&&Object.values(v.basic_info).every(x=>x===null||['string','number','boolean'].includes(typeof x))&&
    object(v.field_sources)&&Object.values(v.field_sources).every(x=>object(x)&&(x.native_id===null||hyLayerIdentifier(x.native_id))&&(x.source_event_ids===null||ids(x.source_event_ids)));
  return v.item_id===v.native_id;
}
function base(v:unknown,layer:HyLayerId):v is Record<string,unknown> {
  return object(v)&&v.schema_version===1&&v.layer===layer&&oneOf(v.sdk_support,['implemented','historical','reserved'])&&
    oneOf(v.generation_state,['configured','disabled','historical','reserved','unknown'])&&oneOf(v.read_status,['readable','partial','unavailable'])&&
    oneOf(v.data_state,['present','empty','unknown'])&&oneOf(v.coverage,['vdb_complete','vdb_only_graph_unopened','unavailable'])&&
    (v.reason_code===null||typeof v.reason_code==='string')&&typeof v.observed_at==='string'&&time(v.observed_at);
}
const invalid=()=>new HyLayerContractError('分层响应与请求范围或协议不一致，已停止展示，未按空层解释。');
export function parseHyLayerPage(v:unknown,layer:HyLayerId,offset:number,state:HyLayerState):HyLayerPage {
  if(!base(v,layer)||!Array.isArray(v.items)||!v.items.every(x=>record(x,layer))||!integer(v.limit,1,50)||!integer(v.offset,0,10000)||v.offset!==offset||v.state!==state||
    !(v.total===null||integer(v.total))||!(v.has_more===null||typeof v.has_more==='boolean')||v.items.length>v.limit||
    !oneOf(v.count_scope,['aggregate_profile','owner_agent_source_layer_state_vdb'])||
    (layer==='l0_basic_info'?(state!=='all'||v.count_scope!=='aggregate_profile'):v.count_scope!=='owner_agent_source_layer_state_vdb')||
    (v.read_status==='unavailable'&&(v.items.length>0||v.total!==null||v.has_more!==null))||
    (v.coverage!=='vdb_complete'&&v.total!==null)||
    new Set(v.items.map(x=>x.item_id)).size!==v.items.length)throw invalid();
  return v as unknown as HyLayerPage;
}
export function parseHyLayerDetail(v:unknown,layer:HyLayerId,id:string):HyLayerDetail {
  if(!base(v,layer)||!(v.item===null||record(v.item,layer))||
    (object(v.item)&&v.item.item_id!==id)||!(v.versions===null||Array.isArray(v.versions)&&v.versions.every(x=>record(x,layer)))||
    (v.read_status==='unavailable'&&v.item!==null)||
    (Array.isArray(v.versions)&&(layer!=='l0_basic_info'||id!=='profile')))throw invalid();
  return v as unknown as HyLayerDetail;
}
