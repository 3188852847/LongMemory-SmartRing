import {useEffect, useState} from 'react';
import {Alert, Button, Radio, Select, Space} from 'antd';
import {useQuery} from '@tanstack/react-query';
import {ChatApi} from '../../api';
import type {InteractionState, SystemState} from '../../pages/RoundDisplayApp';

export const ottoNames = ['neutral','happy','laughing','funny','sad','angry','crying','loving','embarrassed','surprised','shocked','thinking','winking','cool','relaxed','delicious','kissy','confident','sleepy','silly','confused'] as const;
const labels = ['平静','开心','大笑','逗趣','难过','生气','哭泣','喜爱','害羞','惊讶','震惊','思考','眨眼','酷','放松','美味','亲吻','自信','困倦','淘气','困惑'];
export type OttoFace = typeof ottoNames[number];
type Inventory = {commit:string; valid_count:number; items:{name:string;valid:boolean}[]};
const api = new ChatApi();

/** 对齐 otto_state.h 的显示优先级；网页阶段键不产生任何设备协议。 */
export function resolveOttoFace(interaction:InteractionState, system:SystemState, emotion:OttoFace, interruptHint:boolean):OttoFace {
  if (system === 'network_offline' || system === 'server_unavailable') return 'sad';
  if (system === 'model_unavailable' || interaction === 'error') return 'confused';
  if (system === 'provisioning' || system === 'updating') return 'neutral';
  if (interaction === 'thinking') return 'thinking';
  if (interaction === 'speaking') return emotion;
  if (interaction === 'interrupted' && interruptHint) return 'surprised';
  return 'neutral';
}

function useStaticFrame() {
  const [reduced, setReduced] = useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'reduce');
  const [hidden, setHidden] = useState(document.hidden);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches || document.documentElement.dataset.motion === 'reduce');
    const visibility = () => setHidden(document.hidden);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {attributes:true, attributeFilter:['data-motion']});
    media.addEventListener('change', update);
    document.addEventListener('visibilitychange', visibility);
    update();
    return () => {observer.disconnect(); media.removeEventListener('change', update); document.removeEventListener('visibilitychange', visibility);};
  }, []);
  return reduced || hidden;
}

export function OttoPreview({ready, interaction, system, caption}:{ready:boolean;interaction:InteractionState;system:SystemState;caption:string}) {
  const [mode, setMode] = useState('state');
  const [manual, setManual] = useState<OttoFace>('neutral');
  const [emotion, setEmotion] = useState<OttoFace>('neutral');
  const [paused, setPaused] = useState(false);
  const [interruptHint, setInterruptHint] = useState(false);
  const [failed, setFailed] = useState<string[]>([]);
  const staticFrame = useStaticFrame() || paused;
  const inventory = useQuery({queryKey:['otto-preview'], queryFn:()=>api.request<Inventory>('/api/otto-preview'), enabled:ready, retry:false});
  useEffect(() => {
    setInterruptHint(interaction === 'interrupted');
    if (interaction !== 'interrupted') return;
    const timer = window.setTimeout(()=>setInterruptHint(false),650);
    return () => window.clearTimeout(timer);
  }, [interaction]);
  // 离开说话/思考即清空，旧轮情绪不会覆盖聆听或下一轮说话。
  useEffect(() => {if (interaction !== 'speaking' && interaction !== 'thinking') setEmotion('neutral');},[interaction]);
  const requested = mode === 'manual' ? manual : resolveOttoFace(interaction,system,emotion,interruptHint);
  const valid = (name:string) => inventory.data?.items?.some(item=>item.name === name && item.valid);
  const sourceFor = (name:string) => `/api/otto-preview/${name}/${staticFrame ? 'still' : 'loop'}.gif`;
  const available = (name:string) => valid(name) && !failed.includes(sourceFor(name));
  const face = available(requested) ? requested : available('neutral') ? 'neutral' : undefined;
  const src = face ? sourceFor(face) : undefined;
  const choices = ottoNames.map((value,index)=>({value,label:`${labels[index]} · ${value}`}));
  return <section className="otto-preview" aria-label="Otto 原图预览">
    <div className="otto-screen" aria-label="360 黑圆，240 原图居中">
      {src ? <img key={src} src={src} width={240} height={240} alt={`Otto ${face} ${staticFrame?'静态首帧':'原始循环'}`} onError={()=>setFailed(current=>current.includes(src)?current:[...current,src])}/>
        : <span role="status">{!ready || inventory.isLoading ? '正在核对素材…' : '素材不可用'}</span>}
    </div>
    <p className="otto-caption" role="status">{caption} · {face ?? '无可用表情'}{face && face !== requested ? `（${requested} 不可用，回退平静）` : ''} · {staticFrame?'静态首帧':'原图循环'}</p>
    <Space wrap><Button aria-pressed={paused} onClick={()=>setPaused(value=>!value)}>{paused?'播放动画':'暂停动画'}</Button>
      <Button aria-label="重新核对素材" loading={inventory.isFetching} disabled={!ready} onClick={()=>{setFailed([]);void inventory.refetch();}}>重新核对素材</Button></Space>
    {inventory.isError && <Alert type="warning" title="素材清单读取失败" description="请重新核对；这不表示圆屏故障。"/>}
    {inventory.isSuccess && inventory.data.valid_count !== 21 && <Alert type="warning" title={`可用素材 ${inventory.data.valid_count}/21`} description="缺失或指纹不符的素材不会显示；优先回退平静，仍不可用则显示文字。"/>}
    <Radio.Group aria-label="Otto 预览方式" value={mode} onChange={event=>setMode(event.target.value)} options={[{value:'state',label:'跟随网页阶段'},{value:'manual',label:'逐张素材检查'}]}/>
    <label>{mode === 'manual' ? '循环表情' : '本轮说话情绪'}<Select className="wide" virtual={false} aria-label={mode === 'manual'?'循环表情':'本轮说话情绪'} options={choices} value={mode === 'manual'?manual:emotion} disabled={mode === 'state' && interaction !== 'speaking' && interaction !== 'thinking'} onChange={value=>mode === 'manual'?setManual(value):setEmotion(value)}/></label>
    <small>原图 240×240 居中于 360×360 黑圆，四周各留 60 px。减少动态时仅显示原图首帧。网页选择与皮肤颜色不改变固件 Otto。</small>
    <details><summary>状态映射与素材来源</summary><p>待机、启动、唤醒、聆听、没听清 → neutral；思考 → thinking；说话 → 本轮情绪；打断 → surprised 650 毫秒后 neutral；错误 → confused；网络/电脑服务离线 → sad。配网、更新仅在网页说明状态，表情用 neutral。</p><p>对齐 0015 的 otto_state.h 显示规则，保留 L 预览的逐张检查。这里不演示 L 的提议超时，不确认真实采集、连接、播放或设备当前状态。</p><p>txp666/otto-emoji-gif-component · MIT · 固定提交 <code>970cf66906d7c30059faa2704e7002f06b8c3619</code>。清单可用性来自本次文件核验，图像显示仍需浏览器解码。</p></details>
  </section>;
}
