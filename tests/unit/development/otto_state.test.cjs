const { test } = require('node:test');
const assert = require('node:assert/strict');
const S = require('../../../firmware/smartring_plus/previews/otto/state.js');
const Lifecycle = require('../../../firmware/smartring_plus/previews/otto/lifecycle.js');
const run = (...events) => events.reduce((s,e) => S.step(s,typeof e==='string'?{type:e}:e,100),S.initial());

test('recognized input, emotion, TTS, and stop follow one turn',()=>{
  let s=run('listen','stt',{type:'emotion',name:'happy'});
  assert.equal(s.state,'thinking');assert.equal(S.face(s),'thinking');
  s=S.step(s,{type:'tts.start'},200);assert.equal(S.face(s),'happy');
  s=S.step(s,{type:'tts.stop'},300);assert.equal(s.state,'listening');assert.equal(S.face(s),'neutral');
});
test('interrupt clears old emotion and ignores late emotion and TTS stop',()=>{
  let s=run('listen','stt','tts.start',{type:'emotion',name:'angry'},'interrupt');
  assert.equal(s.state,'interrupted');assert.equal(S.face(s),'surprised');
  s=S.step(s,{type:'tick'},751);assert.equal(s.state,'listening');
  s=S.step(s,{type:'emotion',name:'angry'},800);assert.equal(S.face(s),'neutral');
  s=S.step(s,{type:'tts.stop'},800);assert.equal(s.state,'listening');
});
test('interrupt without active speaking does not invent an abort',()=>{
  assert.equal(run('interrupt').state,'idle');assert.equal(run('listen','interrupt').state,'listening');
});
test('faults preempt interaction and remain until explicit recovery',()=>{
  for(const event of ['error','disconnect']){
    let s=run('listen','stt','tts.start',event,'listen','tts.start',{type:'emotion',name:'happy'});
    assert.equal(s.state,event==='error'?'error':'disconnected');
    s=S.step(s,{type:'recover'},100);assert.deepEqual(s,S.initial());
  }
});
test('proposed deadlines fail visibly; listening and speaking do not time out',()=>{
  for(const [event,deadline] of [['connect',15100],['stt',20100]]){
    let s=event==='stt'?run('listen',event):run(event);
    assert.notEqual(S.step(s,{type:'tick'},deadline-1).state,'error');
    assert.equal(S.step(s,{type:'tick'},deadline).state,'error');
  }
  assert.equal(S.step(run('listen'),{type:'tick'},999999).state,'listening');
  assert.equal(S.step(run('tts.start'),{type:'tick'},999999).state,'speaking');
});
test('unknown emotions and out-of-order STT preserve a usable state',()=>{
  assert.equal(run('stt').state,'idle');
  assert.equal(S.face(run('tts.start',{type:'emotion',name:'<invalid>'})),'neutral');
});
test('new listening turn drops previous emotion and all faces are known assets',()=>{
  const s=run('listen','stt',{type:'emotion',name:'loving'},'listen','stt','tts.start');
  assert.equal(S.face(s),'neutral');
  for(const name of S.names)assert.equal(S.face(run('tts.start',{type:'emotion',name})),name);
  for(const state of Object.keys(S.states))assert.ok(S.names.includes(S.face({...S.initial(),state})));
});
test('hidden documents pause and returning visible never resumes automatically',()=>{
  const document=new EventTarget(),preference=new EventTarget();let pauses=0;
  const detach=Lifecycle.attach(document,preference,()=>pauses++);
  document.hidden=false;document.dispatchEvent(new Event('visibilitychange'));assert.equal(pauses,0);
  document.hidden=true;document.dispatchEvent(new Event('visibilitychange'));assert.equal(pauses,1);
  document.hidden=false;document.dispatchEvent(new Event('visibilitychange'));assert.equal(pauses,1);
  detach();document.hidden=true;document.dispatchEvent(new Event('visibilitychange'));assert.equal(pauses,1);
});
test('reduced-motion initial preference and changes pause; disabling never autoplays',()=>{
  const document=new EventTarget(),preference=new EventTarget();let pauses=0;preference.matches=true;
  Lifecycle.attach(document,preference,()=>pauses++);assert.equal(pauses,1);
  const changed=new Event('change');changed.matches=true;preference.dispatchEvent(changed);assert.equal(pauses,2);
  const normal=new Event('change');normal.matches=false;preference.dispatchEvent(normal);assert.equal(pauses,2);
});
