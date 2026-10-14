'use strict';
const S = window.OttoState;
const $ = id => document.getElementById(id);
const labels = ['平静','开心','大笑','逗趣','难过','生气','哭泣','喜爱','害羞','惊讶','震惊','思考','眨眼','酷','放松','美味','亲吻','自信','困倦','淘气','困惑'];
let state = S.initial(), manual = 'neutral', assets = {items:[]}, playing = !matchMedia('(prefers-reduced-motion: reduce)').matches;
let stagesKey = '', gridKey = '', clockOffset = 0;
const media = new Set();
const now = () => performance.now() + clockOffset;
const events = [
  ['idle','待机','已有：SetDeviceState(Idle) / session.idle（仅在聆听时）'],
  ['connect','连接中','已有：SetDeviceState(Connecting)；15 秒超时为提议'],
  ['listen','聆听','已有：SetDeviceState(Listening) / SendStartListening'],
  ['stt','思考','已有：stt.text → SetStatus(思考中)；先进入聆听再触发'],
  ['tts.start','说话','已有：type=tts, state=start → Speaking'],
  ['interrupt','被打断','已有本地路径：Speaking → AbortSpeaking → Listening；650 毫秒提示为提议'],
  ['error','错误','已有：OnNetworkError / Alert；本预览锁定恢复为提议'],
  ['disconnect','断线','提议：确认异常断线后独立显示。已有 OnAudioChannelClosed 回 Idle，也可能是正常会话结束；不可一律视作断线'],
  ['tts.stop','说话结束','已有：tts.stop → Listening（自动模式）；手动模式实际回 Idle']
];

function lookup(name) { return assets.items.find(i => i.name === name); }
function makeMedia(name, grid = false) {
  const box = document.createElement('div'); box.className = 'screen';
  const canvas = document.createElement('canvas'); canvas.width=240; canvas.height=240; canvas.className='bitmap'; canvas.hidden=true;
  const img = document.createElement('img'); img.className='bitmap'; img.alt=`Otto ${name} 原始 GIF`; img.hidden=true;
  const fallback = document.createElement('span'); fallback.className='fallback'; fallback.textContent='素材不可用';
  box.append(canvas,img,fallback);
  let active = name, loaded = false, destroyed = false, triedNeutral = false, visible = true;
  const wantPlay = () => playing && !document.hidden && visible && (!grid || $('grid-play').checked);
  function fail() {
    loaded=false; img.hidden=true;canvas.hidden=true;fallback.hidden=false;
    if (!triedNeutral && active !== 'neutral' && lookup('neutral')?.valid) {
      triedNeutral=true;active='neutral';fallback.textContent='回退 neutral';load();
    } else fallback.textContent='素材不可用';
    box.dataset.fallback=triedNeutral?'neutral':'text';
  }
  function freeze() {
    if (loaded && img.hasAttribute('src')) {
      try {canvas.getContext('2d').drawImage(img,0,0,240,240);canvas.hidden=false;img.hidden=true;img.removeAttribute('src');}
      catch {fail();}
    }
  }
  function load() {
    if (destroyed) return;
    if (!grid && ($('fault').value === 'all' || ($('fault').value === 'missing' && !triedNeutral))) {fail();return;}
    if (!lookup(active)?.valid) {fail();return;}
    img.src=`/gifs/${active}.gif`; img.alt=`Otto ${active} 原始 GIF`;
  }
  img.onload=()=>{if(!grid && $('fault').value==='decode' && !triedNeutral){fail();return;}loaded=true;fallback.hidden=true;box.dataset.asset=active;if(wantPlay()){img.hidden=false;canvas.hidden=true;}else freeze();};
  img.onerror=()=>{if(img.hasAttribute('src'))fail();};
  const instance = {
    box,
    update(){if(wantPlay()){if(loaded && img.hasAttribute('src')){img.hidden=false;canvas.hidden=true;}else load();}else freeze();},
    destroy(){destroyed=true;observer.disconnect();img.removeAttribute('src');media.delete(instance);}
  };
  const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;instance.update();});
  observer.observe(box);media.add(instance);load();return instance;
}
function clearMedia(container) {for(const item of [...media])if(container.contains(item.box))item.destroy();container.replaceChildren();}
function renderStages(name) {
  const key=name+'|'+$('size').value+'|'+$('fault').value;
  if(stagesKey===key)return; stagesKey=key; clearMedia($('stages'));
  const modes=$('size').value==='compare'?['native','scaled']:[$('size').value];
  $('stages').classList.toggle('single',modes.length===1);
  for(const mode of modes){const figure=document.createElement('figure');figure.className='screen-wrap';const m=makeMedia(name);m.box.classList.add(mode);const caption=document.createElement('figcaption');caption.textContent=mode==='native'?'240 原尺寸居中 / 四周各留 60 px':'360 等比放大 / 1.5× / 边缘圆形裁切';figure.append(m.box,caption);$('stages').append(figure);}
}
function render() {
  const name=$('view').value==='manual'?manual:S.face(state);
  $('current-face').textContent=`${name} / ${labels[S.names.indexOf(name)]}`;
  $('current-state').textContent=S.states[state.state][0];
  $('emotion-readout').textContent=`缓存情绪：${state.emotion} · 对话轮次 ${state.turn}`;
  $('play').textContent=playing?'暂停动画':'播放动画';$('play').setAttribute('aria-pressed',String(playing));
  $('decision').textContent=($('view').value==='manual'?'单表情检查：直接循环原 GIF；右侧事件不会改变所选素材。':`方案仲裁：${S.states[state.state][0]} → ${name}${state.deadline?' · 有提议超时/返回':''}。${state.state==='listening'?'正在聆听，晚到的说话情绪不会覆盖此状态。':''}`)+($('fault').value==='none'?'':' 当前为素材故障演练，交互状态不变。');
  for(const button of $('events').children)button.setAttribute('aria-pressed',String(button.dataset.state===state.state));
  for(const button of $('gallery').children)button.setAttribute('aria-pressed',String(button.dataset.name===name));
  renderStages(name);
}
function dispatch(type,name){state=S.step(state,{type,name},now());render();}
function renderGrid(){
  const key=JSON.stringify(assets.items);if(key===gridKey)return;gridKey=key;clearMedia($('gallery'));
  for(const [index,name] of S.names.entries()){
    const item=lookup(name),button=document.createElement('button');button.className='tile';button.dataset.name=name;button.setAttribute('aria-pressed','false');button.setAttribute('aria-label',`预览 ${name} ${labels[index]}`);
    const m=makeMedia(name,true),title=document.createElement('strong'),detail=document.createElement('span');title.textContent=`${labels[index]} / ${name}`;detail.className='small';detail.textContent=item?.valid?`${item.frames} 帧 · ${item.duration_ms} ms · ${item.expected_bytes.toLocaleString()} B`:`待素材 · ${item?.reason||'尚未核对'}`;
    button.append(m.box,title,detail);button.onclick=()=>{manual=name;$('view').value='manual';render();};$('gallery').append(button);
  }
}
async function refresh(){
  $('refresh').disabled=true;
  try{const response=await fetch('/api/assets');if(!response.ok)throw Error('inventory');assets=await response.json();$('asset-status').textContent=assets.valid_count===21?`21 / 21 固定素材指纹与 GIF 结构通过 · ${(assets.total_bytes/1048576).toFixed(2)} MiB · 像素解码待各图加载`:`${assets.valid_count} / 21 素材就绪 · 缺失部分明确回退；等待所有者下载后重新检查`;
    stagesKey='';renderGrid();render();
  }catch{$('asset-status').textContent='素材清单读取失败，请确认此独立预览服务仍在运行。';}
  finally{$('refresh').disabled=false;}
}
for(const [type,label,source] of events){const button=document.createElement('button');button.textContent=label;button.dataset.state=({'connect':'connecting','listen':'listening','stt':'thinking','tts.start':'speaking','interrupt':'interrupted','disconnect':'disconnected'})[type]||type;button.onclick=()=>{$('event-source').textContent=source;dispatch(type);};$('events').append(button);}
for(const [index,name] of S.names.entries()){const option=document.createElement('option');option.value=name;option.textContent=`${labels[index]} / ${name}`;$('emotion').append(option);}
$('send-emotion').onclick=()=>{dispatch('emotion',$('emotion').value);$('event-source').textContent='已有：type=llm, emotion=名称。当前方案仅思考时缓存、说话时显示；聆听/故障时忽略。';};
$('size').onchange=render;$('view').onchange=render;
$('fault').onchange=render;
$('play').onclick=()=>{playing=!playing;for(const m of media)m.update();render();};
$('grid-play').onchange=()=>{for(const m of media)m.update();};
$('refresh').onclick=refresh;
$('recover').onclick=()=>{dispatch('recover');$('event-source').textContent='本地演练恢复：清除故障并回待机；不是设备网络恢复事件。';};
$('timeout').onclick=()=>{if(state.deadline){clockOffset+=Math.max(0,state.deadline-now())+1;dispatch('tick');}else $('event-source').textContent='当前无计时返回点。说话由 tts.stop 结束；聆听不强制超时。';};
function pauseMedia(){playing=false;for(const m of media)m.update();render();}
$('reduce-demo').onclick=()=>{pauseMedia();$('event-source').textContent='本地演练：已走与减少动态偏好相同的暂停路径；系统偏好未更改。可主动播放。';};
window.OttoLifecycle.attach(document,matchMedia('(prefers-reduced-motion: reduce)'),pauseMedia);
setInterval(()=>{const next=S.step(state,{type:'tick'},now());if(next.state!==state.state){state=next;render();}},100);
refresh();
