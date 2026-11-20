import {useEffect, useRef, useState, type PointerEvent} from 'react';
import type {InteractionState} from '../../pages/RoundDisplayApp';

const reactions = {happy:'开心', wink:'眨眼', sleep:'困倦'} as const;
type Reaction = keyof typeof reactions;
type Props = {interaction: InteractionState; blocked: boolean; caption: string; change: (state: InteractionState) => void};

export function WhalePreview({interaction, blocked, caption, change}: Props) {
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const stroke = useRef<{id:number; x:number; y:number; peak:number; direction:number; rubbed:boolean; eligible:boolean} | null>(null);
  useEffect(() => {
    setReaction(null);
    stroke.current = null;
    return () => clearTimeout(timer.current);
  }, [interaction, blocked]);

  function react(face: Reaction) {
    if (blocked || interaction !== 'idle') return;
    clearTimeout(timer.current);
    setReaction(face);
    timer.current = setTimeout(() => setReaction(null), 1800);
  }
  function coordinates(e: PointerEvent<HTMLDivElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    return [(e.clientX-box.left)*360/box.width, (e.clientY-box.top)*360/box.height];
  }
  function down(e: PointerEvent<HTMLDivElement>) {
    if (failed || blocked || !e.isPrimary || e.button !== 0) return;
    const [x,y] = coordinates(e);
    stroke.current = {id:e.pointerId,x,y,peak:x,direction:0,rubbed:false,eligible:interaction==='idle' && x>=101 && x<=255 && y>=85 && y<=213};
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent<HTMLDivElement>) {
    const g = stroke.current;
    if (!g?.eligible || g.id !== e.pointerId) return;
    const [x,y] = coordinates(e);
    if (x<82 || x>275 || y<65 || y>233) {g.eligible=false; return;}
    if (!g.direction) {
      if (Math.abs(x-g.x)<14) return;
      g.direction=Math.sign(x-g.x); g.peak=x;
    } else if ((x-g.peak)*g.direction>0) g.peak=x;
    else if ((g.peak-x)*g.direction>=14) g.rubbed=true;
  }
  function up(e: PointerEvent<HTMLDivElement>) {
    const g=stroke.current;
    if (!g || g.id!==e.pointerId) return;
    stroke.current=null;
    if (g.eligible) react(g.rubbed?'sleep':g.y<151?'happy':'wink');
    else if (interaction==='idle') change('listening');
    else if (interaction==='listening') change('idle');
    else if (interaction==='speaking') change('interrupted');
  }
  const face = reaction ?? (!blocked && interaction==='thinking'?'thinking':'neutral');
  return <>
    <div className="otto-screen whale-touch-screen" aria-label="大肥鱼触摸预览" onPointerDown={down} onPointerMove={move} onPointerUp={up}
      onLostPointerCapture={() => {stroke.current=null;}} onPointerCancel={() => {stroke.current=null;}}>
      {failed ? <button onClick={() => setFailed(false)}>动画未加载，重新读取</button> :
        <img draggable={false} alt="大肥鱼" onError={() => setFailed(true)} src={`/pet/whale/device/${face}.gif`}/>}
      <span className="whale-caption" role="status">{reaction ? reactions[reaction] : caption}</span>
    </div>
    <p className="subtle">轻点头顶或脸颊，按住左右来回揉一下再松手。点下方空白处可模拟开始聊天。</p>
    <div className="whale-actions">{([['happy','摸摸头'],['wink','戳脸'],['sleep','揉一揉']] as const).map(([face,label]) =>
      <button key={face} disabled={blocked || interaction!=='idle'} onClick={() => react(face)}>{label}</button>)}</div>
  </>;
}
