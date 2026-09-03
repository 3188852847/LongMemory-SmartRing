import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {filterRuns, groupLabel, evidenceLabel, renderEvidence, statusLabel} from '../../web/assets/experiment-view.mjs';
test('experiment group identity and absent evidence never mean success',()=>{
  assert.equal(groupLabel('longmemory_v1/dense_cosine'),'规则提取 + 向量');
  assert.equal(evidenceLabel(null),'不适用 / 未提供');
  assert.equal(evidenceLabel(false),'不足');
  assert.equal(statusLabel('incomplete'),'未全部完成');
});
test('fake, real answer and retrieval filters remain separate',()=>{
  const runs=[{id:'1',kind:'answers',provider:'fake',model:'fake'}, {id:'2',kind:'answers',provider:'openai_compatible',model:'DeepSeek'}, {id:'3',kind:'retrieval',provider:'local_embedding',model:'BGE'}];
  assert.deepEqual(filterRuns(runs,'','real').map(r=>r.id),['2']);
  assert.deepEqual(filterRuns(runs,'bge','all').map(r=>r.id),['3']);
  assert.deepEqual(filterRuns(runs,'','fake').map(r=>r.id),['1']);
});
test('experiment evidence remains inert text and all assets local',()=>{
  const doc={createElement(tag){return {tag,children:[],append(...items){this.children.push(...items);}};}};
  const malicious='<img src=x onerror=alert(1)>';
  const node=renderEvidence(doc,{injected_context:malicious,context:malicious,retrieved:[{content:malicious,source_event_ids:['e1']}],sources:[{event_id:'e1',role:'user',content:malicious}]});
  assert.equal(node.children[0].children[1].textContent,malicious);
  const code=readFileSync(new URL('../../web/assets/experiments.js',import.meta.url),'utf8')+readFileSync(new URL('../../web/assets/experiment-view.mjs',import.meta.url),'utf8');
  assert.ok(!/innerHTML|insertAdjacentHTML|localStorage|sessionStorage|eval\(/.test(code));
  const html=readFileSync(new URL('../../web/experiments.html',import.meta.url),'utf8');
  assert.ok(!/(src|href)=["']https?:/.test(html));
  assert.ok(!/setInterval/.test(code));
});
