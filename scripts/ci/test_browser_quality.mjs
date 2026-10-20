import {test} from 'node:test';
import assert from 'node:assert/strict';
import {verifyCollection} from './browser_quality.mjs';

function report(entries) {
  return {config:{projects:[{retries:0}]},suites:entries.map(([file,title,project])=>({title:file,specs:[{file,title,tests:[{projectName:project}]}]}))};
}
test('普通与专用主机完整且不重复的收集可进入运行',()=>{
  assert.equal(verifyCollection(report([['a.spec.ts','业务','chromium'],['q.spec.ts','诊断','observability']]),['a.spec.ts','q.spec.ts']).length,2);
});
test('排除或过滤整份合成spec会失败',()=>{
  assert.throws(()=>verifyCollection(report([['a.spec.ts','业务','chromium']]),['a.spec.ts','q.spec.ts']),/遗漏/);
});
test('继承项目使相同用例跑两遍会失败',()=>{
  assert.throws(()=>verifyCollection(report([['a.spec.ts','业务','chromium'],['a.spec.ts','业务','observability']]),['a.spec.ts']),/重复/);
});
test('收集错误和重试配置都不能进入运行',()=>{
  assert.throws(()=>verifyCollection({...report([]),errors:[{message:'fixture import failed'}]},[]),/收集有错误/);
  const retry=report([['a.spec.ts','业务','chromium']]);retry.config.projects[0].retries=1;
  assert.throws(()=>verifyCollection(retry,['a.spec.ts']),/零重试/);
});
