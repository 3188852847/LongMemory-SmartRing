import {expect,test,vi} from 'vitest';
import {hySemanticTaskIdentifier,hySemanticTaskPathIdentifier,parseHySemanticStatus,parseHySemanticTask} from './hySemantic';
import {ChatApi} from './client';
import {MemoryEngineApi} from './memoryEngine';
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
  expect(hySemanticTaskIdentifier('a'.repeat(256))).toBe(true);expect(hySemanticTaskIdentifier('a'.repeat(257))).toBe(false);
  expect(hySemanticTaskIdentifier('add:'+'a'.repeat(64)+':expiry')).toBe(true);
  expect(hySemanticTaskIdentifier('😀'.repeat(256))).toBe(true);expect(hySemanticTaskIdentifier('😀'.repeat(257))).toBe(false);
  for(const id of ['', ' \u0085\u3000', 'bad\u001fid'])expect(hySemanticTaskIdentifier(id)).toBe(false);
  expect(hySemanticTaskIdentifier('../other-task')).toBe(true); // 原生ID与HTTP路径边界分开。
  for(const id of ['../other-task','other\\task','.','..'])expect(hySemanticTaskPathIdentifier(id)).toBe(false);
});

test.each(['add:'+'a'.repeat(64)+':expiry','management:synthetic-operation','原生任务:100%?尾#'])('自动任务ID按单路径段编码GET且不改变原ID：%s',async id=>{
  const request=vi.fn(async()=>semanticTaskFixture({task_id:id}));
  const api=new MemoryEngineApi({request} as unknown as ChatApi);
  expect((await api.semanticTask(id)).task_id).toBe(id);
  expect(request.mock.calls).toEqual([[`/api/memory-engine/hy/semantic/tasks/${encodeURIComponent(id)}`]]);
});

test('路径分隔或穿越ID在HTTP调用前拒绝，无任务执行副作用',async()=>{
  const request=vi.fn();const api=new MemoryEngineApi({request} as unknown as ChatApi);
  for(const id of ['../task','a/b','a\\b','.','..'])await expect(api.semanticTask(id)).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
});
