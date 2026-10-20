import {expect,test} from 'vitest';
import {hySemanticTaskIdentifier,parseHySemanticStatus,parseHySemanticTask} from './hySemantic';
import {disabledSemanticStatus,semanticStatusFixture,semanticTaskFixture} from '../tests/fixtures/hySemantic';

test('AI扁平导出兼容AB启用/禁用状态，空任务映射不补零',()=>{
  expect(parseHySemanticStatus(semanticStatusFixture()).enabled).toBe(true);
  const disabled=parseHySemanticStatus(disabledSemanticStatus());expect(disabled.task_counts.running).toBeUndefined();expect(disabled.epoch).toBeNull();
  expect(()=>parseHySemanticStatus({schema_version:1,status:semanticStatusFixture()})).toThrow();
});
test('旧协议、伪执行授权、未知策略与错误计数拒绝，不作为能力成功',()=>{
  for(const patch of [{protocol:1},{execution_authorized:true},{proactive_contact_enabled:true},{intention_read:'search_and_write'},{expired_intention_policy:'completed'},{task_counts:{running:-1}},{observed_at:null},{runtime:{write_enabled:'true',use_enabled:true}}])
    expect(()=>parseHySemanticStatus({...semanticStatusFixture(),...patch})).toThrow();
});
test('单任务与精确请求ID一致，未完成时间保持空，耗时允许真实小数',()=>{
  const value=semanticTaskFixture({state:'running',finished_at:null,elapsed_ms:null});
  expect(parseHySemanticTask(value,value.task_id).finished_at).toBeNull();
  expect(()=>parseHySemanticTask(value,'different-task')).toThrow();
  expect(()=>parseHySemanticTask({...value,reason_code:'private exception body and path'},value.task_id)).toThrow();
  expect(parseHySemanticTask(semanticTaskFixture(),value.task_id).elapsed_ms).toBe(12.5);
  expect(hySemanticTaskIdentifier('a'.repeat(96))).toBe(true);expect(hySemanticTaskIdentifier('a'.repeat(97))).toBe(false);
  expect(hySemanticTaskIdentifier('namespace:task')).toBe(false);expect(hySemanticTaskIdentifier('../other-task')).toBe(false);
});
