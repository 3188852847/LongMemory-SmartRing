import test from 'node:test';
import assert from 'node:assert/strict';
import {normalize, read, save, apply, KEY} from '../../web/assets/appearance.mjs';

test('appearance accepts only enumerated presentation values', () => {
  assert.deepEqual(normalize({theme:'<script>',size:999,motion:'spin'}),
    {theme:'system',size:'normal',motion:'system'});
  assert.deepEqual(normalize(null),{theme:'system',size:'normal',motion:'system'});
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
test('system preference and explicit overrides apply without html', () => {
  const root = {dataset:{}};
  apply(root,{theme:'system',size:'larger',motion:'system'},true,true);
  assert.deepEqual(root.dataset,{theme:'dark',reading:'larger',motion:'reduce'});
  apply(root,{theme:'light',size:'normal',motion:'full'},true,true);
  assert.equal(root.dataset.theme,'light');
  assert.equal(root.dataset.motion,'full');
});
