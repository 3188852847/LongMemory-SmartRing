/** AA schema 1：只读装配目录，不是运行 trace、库计数或 worker 健康报告。 */
export type HyIntegration='configured'|'disabled'|'not_integrated'|'reserved'|'unknown';
export type HySdkSupport='implemented'|'reserved'|'platform';
export interface HyCatalogItem {id:string;title:string;sdk_support:HySdkSupport;integration:HyIntegration;description:string;evidence:string[]}
export interface HyLayer extends HyCatalogItem {number:number;count:null}
export interface HyMechanism extends HyCatalogItem {group:string;endpoints:string[]}
export interface HyMechanismsSnapshot {
  schema_version:1;sdk:{version:'2.0.3';source_commit:'2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed'};
  observed_at:string;scope:'adapter_declaration_and_runtime_gates';assembly:'standard_worker'|'custom_or_unknown';
  mode:'lite'|'pro'|'ultra'|null;scene:'chat'|null;
  runtime:{write_enabled:boolean;use_enabled:boolean;engine_initialized:boolean;worker_health:'unknown'};
  modes:Array<{id:string;title:string;description:string;selected:boolean|null}>;
  layers:HyLayer[];mechanisms:HyMechanism[];evidence_gaps:string[];
}
export class HyMechanismsContractError extends Error {}
const object=(value:unknown):value is Record<string,unknown>=>Boolean(value)&&typeof value==='object'&&!Array.isArray(value);
const strings=(value:unknown):value is string[]=>Array.isArray(value)&&value.every(item=>typeof item==='string');
const text=(value:unknown):value is string=>typeof value==='string'&&value.trim().length>0;
function catalogItem(value:unknown):boolean {
  return object(value)&&text(value.id)&&text(value.title)&&typeof value.description==='string'&&
    ['implemented','reserved','platform'].includes(String(value.sdk_support))&&
    ['configured','disabled','not_integrated','reserved','unknown'].includes(String(value.integration))&&strings(value.evidence)&&
    value.evidence.every(path=>!/^([a-z]+:|[\/]|\.\.)/i.test(path));
}
export function parseHyMechanisms(value:unknown):HyMechanismsSnapshot {
  if(!object(value)||value.schema_version!==1||!object(value.sdk)||value.sdk.version!=='2.0.3'||
    value.sdk.source_commit!=='2a4c5e38e78a42ae0acae1fe6f12cfcd8ecb64ed'||
    value.scope!=='adapter_declaration_and_runtime_gates'||!text(value.observed_at)||Number.isNaN(Date.parse(value.observed_at))||
    !['standard_worker','custom_or_unknown'].includes(String(value.assembly))||
    ![null,'lite','pro','ultra'].includes(value.mode as null|string)||![null,'chat'].includes(value.scene as null|string)||
    !object(value.runtime)||['write_enabled','use_enabled','engine_initialized'].some(key=>typeof value.runtime!=='object'||typeof (value.runtime as Record<string,unknown>)[key]!=='boolean')||
    value.runtime.worker_health!=='unknown'||!strings(value.evidence_gaps)||
    !Array.isArray(value.modes)||!value.modes.every(mode=>object(mode)&&text(mode.id)&&text(mode.title)&&typeof mode.description==='string'&&(mode.selected===null||typeof mode.selected==='boolean'))||
    !Array.isArray(value.layers)||!value.layers.every(layer=>catalogItem(layer)&&object(layer)&&Number.isInteger(layer.number)&&Number(layer.number)>=0&&Number(layer.number)<=7&&layer.count===null)||
    !Array.isArray(value.mechanisms)||!value.mechanisms.every(item=>catalogItem(item)&&object(item)&&text(item.group)&&strings(item.endpoints))) {
    throw new HyMechanismsContractError('机制快照结构或固定版本不匹配，未将它当作当前运行事实。');
  }
  if(new Set(value.layers.map(layer=>layer.id)).size!==value.layers.length||new Set(value.layers.map(layer=>layer.number)).size!==value.layers.length||new Set(value.mechanisms.map(item=>item.id)).size!==value.mechanisms.length)throw new HyMechanismsContractError('机制快照包含重复标识，未展示冲突目录。');
  return value as unknown as HyMechanismsSnapshot;
}
