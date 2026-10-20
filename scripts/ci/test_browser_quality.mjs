import {test} from 'node:test';
import assert from 'node:assert/strict';
import {verifyCollection} from './browser_quality.mjs';
import {testPort} from './browser_test_ports.mjs';

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
test('普通/诊断默认端口保持，全部已知日用端口均拒绝',()=>{
  assert.equal(testPort(undefined,18777),18777);
  assert.equal(testPort(undefined,18892),18892);
  for(const port of [8000,8003,8766,8767,8768,18000,18003,18767,18770]) {
    assert.throws(()=>testPort(String(port),18777),/独立/);
    assert.throws(()=>testPort(undefined,port),/独立/);
  }
  assert.equal(testPort('19871',18777),19871);
});
test('无效合成端口在启动任何主机前拒绝',()=>{
  for(const port of ['', '1023','65536','1.5','NaN'])assert.throws(()=>testPort(port,18777),/独立/);
});
