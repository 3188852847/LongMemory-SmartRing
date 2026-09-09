import test from 'node:test';
import assert from 'node:assert/strict';
import {normalize, read, save, apply, KEY, LEGACY_KEY} from '../../web/assets/appearance.mjs';

test('appearance accepts only enumerated presentation values', () => {
  assert.deepEqual(normalize({theme:'<script>',size:999,motion:'spin'}),
    {theme:'future',size:'normal',motion:'system'});
  assert.deepEqual(normalize(null),{theme:'future',size:'normal',motion:'system'});
  assert.equal(normalize({theme:'future'}).theme,'future');
});
test('save/reload restores only display settings', () => {
  let raw;
  const storage = {getItem:()=>raw,setItem:(key,value)=>{assert.equal(key,KEY);raw=value;}};
  assert.equal(save(storage,{theme:'dark',size:'large',motion:'reduce',secret:'excluded'}),true);
  assert.deepEqual(read(storage),{theme:'dark',size:'large',motion:'reduce'});
  assert.ok(!raw.includes('secret'));
});
test('disabled or corrupt storage falls back without blocking chat', () => {
  assert.deepEqual(read({getItem:()=>'{'}),normalize(null));
  assert.equal(save(undefined,{}),false);
});
test('legacy appearance keeps reading preferences and adopts the future theme', () => {
  const legacy = JSON.stringify({theme:'light',size:'large',motion:'reduce'});
  const storage = {getItem:key=>key === LEGACY_KEY ? legacy : null};
  assert.deepEqual(read(storage),{theme:'future',size:'large',motion:'reduce'});
});
test('system preference and explicit overrides apply without html', () => {
  const root = {dataset:{}};
  apply(root,{theme:'system',size:'larger',motion:'system'},true,true);
  assert.deepEqual(root.dataset,{theme:'dark',reading:'larger',motion:'reduce'});
  apply(root,{theme:'light',size:'normal',motion:'full'},true,true);
  assert.equal(root.dataset.theme,'light');
  assert.equal(root.dataset.motion,'full');
});
