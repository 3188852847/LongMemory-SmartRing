import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {jobStatus, progressText, quoteText} from '../../web/assets/experiment-jobs.mjs';

test('job progress separates attempts, failures and correctness',()=>{
  assert.match(progressText({attempts:3,total:32,completed:1,failed:1}),/已尝试 3\/32/);
  assert.match(progressText({attempts:3,total:32,completed:1,failed:1}),/未结束 30/);
  assert.match(jobStatus('interrupted'),/未自动续跑/);
  assert.equal(jobStatus('invented'),'状态未知');
});
test('quote gives bounded requests and character budget without price invention',()=>{
  const text=quoteText({model:{model:'Fake'},groups:[1,2,3,4],question_count:8,total:32,context_chars:4000});
  assert.match(text,/最多 32 次/);assert.match(text,/4000 字符/);assert.match(text,/新增提取 0 次/);
});
test('job client uses local assets, text sinks and explicit confirmation',()=>{
  const code=readFileSync(new URL('../../web/assets/experiment-jobs.mjs',import.meta.url),'utf8');
  assert.ok(!/innerHTML|insertAdjacentHTML|localStorage|sessionStorage|eval\(|setInterval/.test(code));
  assert.match(code,/requestId=crypto.randomUUID/);
  assert.match(code,/if\(submitting\|\|!quote\|\|!\$\('job-consent'\)\.checked\)return/);
  assert.match(code,/\/api\/experiment-jobs\/start/);
  const html=readFileSync(new URL('../../web/experiments.html',import.meta.url),'utf8');
  assert.match(html,/<dialog id="job-confirm"/);
  assert.match(html,/id="job-start"[^>]+disabled/);
});
