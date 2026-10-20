import type {HyLayerDetail,HyLayerId,HyLayerPage,HyLayerRead,HyStoredRecord} from '../../api/hyLayerData';

/** 依据 AA schema 1 的纯合成数据；不来自个人库或真实原话。 */
export function storedRecord(layer:HyLayerId,index=0,patch:Partial<HyStoredRecord>={}):HyStoredRecord {
  const id=`synthetic-${layer}-${index}`;
  return {item_id:id,native_id:id,kind:'stored_record',layer,content:`合成 ${layer} 保存正文 ${index}：周末沿河散步。`,content_chars:35,content_truncated:false,
    status:'active',is_latest:true,recorded_at:'2026-10-20T10:20:00+00:00',memory_at:null,valid_from:null,valid_until:null,
    supersedes:[],superseded_by:[],version_links_limited:false,source_event_ids:['synthetic-platform-source'],source_raw_memory_id:null,...patch};
}
export function layerRead(layer:HyLayerId,patch:Partial<HyLayerRead>={}):HyLayerRead {
  return {schema_version:1,layer,sdk_support:layer==='l4_identity'?'historical':layer==='l5_knowledge'?'reserved':'implemented',
    generation_state:layer==='l4_identity'?'historical':layer==='l5_knowledge'?'reserved':['l6_schema','l7_intention'].includes(layer)?'disabled':'configured',
    read_status:'readable',data_state:'present',coverage:'vdb_complete',reason_code:null,observed_at:'2026-10-21T03:20:00+00:00',...patch};
}
export const profileRecord:HyStoredRecord=storedRecord('l0_basic_info',0,{
  item_id:'profile',native_id:'synthetic-profile-head',kind:'aggregate_profile',content:'喜欢的饮品：茶\n常住城市：合成城市',stored_version_count:2,
  basic_info:{喜欢的饮品:'茶',常住城市:'合成城市',待填字段:null,空文本字段:''},
  field_sources:{喜欢的饮品:{native_id:'synthetic-profile-old',source_event_ids:['synthetic-platform-source']},常住城市:{native_id:'synthetic-profile-head',source_event_ids:null},待填字段:{native_id:null,source_event_ids:null},空文本字段:{native_id:null,source_event_ids:null}},
  source_event_ids:null,
});
export const profileVersions=[storedRecord('l0_basic_info',0,{item_id:'synthetic-profile-old',native_id:'synthetic-profile-old',content:'喜欢的饮品：茶',status:'superseded',is_latest:false,superseded_by:['synthetic-profile-head']}),
  storedRecord('l0_basic_info',1,{item_id:'synthetic-profile-head',native_id:'synthetic-profile-head',content:'常住城市：合成城市',supersedes:['synthetic-profile-old']})];
export function layerPage(layer:HyLayerId,patch:Partial<HyLayerPage>={}):HyLayerPage {
  return {...layerRead(layer),items:layer==='l0_basic_info'?[profileRecord]:[storedRecord(layer)],limit:20,offset:0,state:'all',total:1,has_more:false,
    count_scope:layer==='l0_basic_info'?'aggregate_profile':'owner_agent_source_layer_state_vdb',...patch};
}
export function layerDetail(layer:HyLayerId,item:HyStoredRecord=storedRecord(layer),patch:Partial<HyLayerDetail>={}):HyLayerDetail {
  return {...layerRead(layer),item,versions:item.kind==='aggregate_profile'?profileVersions:null,...patch};
}
