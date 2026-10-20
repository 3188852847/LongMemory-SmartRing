import {expect,test} from 'vitest';
import {parseHyLayerDetail,parseHyLayerPage} from './hyLayerData';
import {graphPage,layerDetail,layerPage,semanticRecord,storedRecord} from '../tests/fixtures/hyLayerData';

test('AB原生图页和图计数范围；旧VDB共存时只保留部分覆盖及未知总数',()=>{
  expect(parseHyLayerPage(graphPage(),'l6_schema',0,'all').coverage).toBe('graph_complete');
  const partial=graphPage({coverage:'graph_only_legacy_vdb_present',read_status:'partial',reason_code:'legacy_vdb_schema_not_in_graph_page',total:null});
  expect(parseHyLayerPage(partial,'l6_schema',0,'all').total).toBeNull();
  expect(()=>parseHyLayerPage({...partial,total:1},'l6_schema',0,'all')).toThrow();
  expect(()=>parseHyLayerPage({...partial,count_scope:'owner_agent_source_layer_state_vdb'},'l6_schema',0,'all')).toThrow();
  expect(()=>parseHyLayerPage({...partial,read_status:'readable'},'l6_schema',0,'all')).toThrow();
  expect(()=>parseHyLayerPage(layerPage('l7_intention',{coverage:'graph_complete'}),'l7_intention',0,'all')).toThrow();
});

test('语义字段整组校验、来源有界、无执行授权；兼容旧页缺整组字段',()=>{
  const item=semanticRecord('l6_schema',{derivation_state:'isolated',evidence_memory_ids:null,updated_at:null});
  expect(parseHyLayerDetail(layerDetail('l6_schema',item),'l6_schema',item.item_id).item?.updated_at).toBeNull();
  for(const patch of [{execution_authorized:true},{semantic_kind:'future_intention'},{derivation_state:'expired'},{evidence_memory_ids:Array(17).fill('synthetic')},{updated_at:'not-a-time'},{evidence_memory_ids:undefined}])
    expect(()=>parseHyLayerDetail(layerDetail('l6_schema',{...item,...patch} as never),'l6_schema',item.item_id)).toThrow();
  expect(parseHyLayerPage(layerPage('l6_schema'),'l6_schema',0,'all').items[0].semantic_kind).toBeUndefined();
});

test('L7到期是原生意图状态，不接受L6派生状态或执行授权',()=>{
  const item=semanticRecord('l7_intention',{derivation_state:'expired',valid_until:'2026-10-20T04:00:00Z'});
  expect(parseHyLayerDetail(layerDetail('l7_intention',item),'l7_intention',item.item_id).item?.derivation_state).toBe('expired');
  expect(()=>parseHyLayerDetail(layerDetail('l7_intention',{...item,derivation_state:'ready'}),'l7_intention',item.item_id)).toThrow();
});

test.each(['l2_fact','l3_summary','l4_identity'] as const)('%s来源四字段独立校验，旧响应缺标签不补完整',layer=>{
  const record=storedRecord(layer);
  const p={status:'model_inference_unverified' as const,semantic_source_complete:false,dependency_basis:'scope_context_envelope' as const,injection_allowed:true};
  expect(parseHyLayerPage(layerPage(layer,{items:[{...record,provenance:p}]}),layer,0,'all').items[0].provenance?.injection_allowed).toBe(true);
  expect(parseHyLayerPage(layerPage(layer),layer,0,'all').items[0].provenance).toBeUndefined();
  for(const bad of [{...p,semantic_source_complete:true},{...p,injection_allowed:'true'},{...p,status:'confirmed'},{status:p.status},{...p,private_field:'hidden'}])
    expect(()=>parseHyLayerDetail(layerDetail(layer,{...record,provenance:bad} as never),layer,record.item_id)).toThrow();
});
