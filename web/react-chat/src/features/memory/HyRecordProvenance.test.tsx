import {expect,test} from 'vitest';
import {render,screen} from '@testing-library/react';
import {profileRecord,semanticRecord,storedRecord} from '../../tests/fixtures/hyLayerData';
import {HyRecordProvenance} from './HyRecordProvenance';

test('缺来源标签时三个判断保持未知，不从FACT层名或active补造可信',()=>{
  render(<HyRecordProvenance item={storedRecord('l2_fact')} detail/>);
  expect(screen.getByText('来源可信类型未知')).toBeTruthy();expect(screen.getByText('注入许可未知')).toBeTruthy();
  expect(screen.getAllByText('未知',{exact:true})).toHaveLength(2);expect(screen.queryByText('已证实完整')).toBeNull();
});
test('未证实推断与是否可注入独立，潜在依赖不能标成真实引用',()=>{
  render(<HyRecordProvenance item={storedRecord('l3_summary',0,{provenance:{status:'model_inference_unverified',semantic_source_complete:false,dependency_basis:'scope_context_envelope',injection_allowed:true}})} detail/>);
  expect(screen.getByText('未证实模型推断')).toBeTruthy();expect(screen.getByText('当前允许注入')).toBeTruthy();
  expect(screen.getByText('尚未证实完整')).toBeTruthy();expect(screen.getByText('潜在上下文依赖')).toBeTruthy();
  expect(screen.getByText(/不是模型真实引用或逐句归因/)).toBeTruthy();
});
test.each([['verbatim_user','raw_exact_match','用户原话'],['explicit_correction','explicit_correction','用户明确纠正']] as const)('%s来源标签和注入禁止独立', (status,dependency_basis,label)=>{
  render(<HyRecordProvenance item={storedRecord('l4_identity',0,{provenance:{status,semantic_source_complete:true,dependency_basis,injection_allowed:false}})} detail/>);
  expect(screen.getAllByText(label).length).toBeGreaterThan(0);expect(screen.getByText('当前禁止注入')).toBeTruthy();
  expect(screen.getByText('已证实完整')).toBeTruthy();expect(screen.queryByText('未证实模型推断')).toBeNull();
  expect(screen.getByText(/不代表未来意图已执行/)).toBeTruthy();
});
test('旧未观测依赖保持未证实，非来源契约层不套用标签',()=>{
  const view=render(<HyRecordProvenance item={storedRecord('l2_fact',0,{provenance:{status:'model_inference_unverified',semantic_source_complete:false,dependency_basis:'legacy_unobserved',injection_allowed:false}})} detail/>);
  expect(screen.getByText(/历史依赖没有被观测/)).toBeTruthy();view.rerender(<HyRecordProvenance item={storedRecord('l6_schema')} detail/>);
  expect(screen.queryByLabelText('来源可信类型与注入许可')).toBeNull();
});

test('L0聚合有来源标签也不能认定整份画像来源完整；缺标签保持未知',()=>{
  const view=render(<HyRecordProvenance item={{...profileRecord,provenance:{status:'verbatim_user',semantic_source_complete:true,dependency_basis:'raw_exact_match',injection_allowed:true}}} detail/>);
  expect(screen.getByText(/不能证明整份聚合画像的语义来源完整/)).toBeTruthy();expect(screen.getByText('记录级语义来源完整性')).toBeTruthy();
  view.rerender(<HyRecordProvenance item={profileRecord} detail/>);expect(screen.getByText('注入许可未知')).toBeTruthy();expect(screen.queryByText('已证实完整')).toBeNull();
});
test('L7同四字段区分来源和注入，不宣称未来意图已执行',()=>{
  render(<HyRecordProvenance item={semanticRecord('l7_intention',{provenance:{status:'model_inference_unverified',semantic_source_complete:false,dependency_basis:'scope_context_envelope',injection_allowed:false}})} detail/>);
  expect(screen.getByText('未证实模型推断')).toBeTruthy();expect(screen.getByText('当前禁止注入')).toBeTruthy();expect(screen.getByText(/不代表未来意图已执行/)).toBeTruthy();
});
