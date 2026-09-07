import {useEffect, useRef, useState} from 'react';
import {Button, Space, Switch} from 'antd';
import {ChatApi} from './api';

/** 网页朗读只在电脑播放。可选麦克风检测到连续讲话能量后停止播放，不向服务端上传麦克风。 */
export function SpeechPlayer({api, text}: {api:ChatApi; text:string}) {
  const audio = useRef<HTMLAudioElement|undefined>(undefined);
  const objectUrl = useRef<string|undefined>(undefined);
  const stream = useRef<MediaStream|undefined>(undefined);
  const frame = useRef(0), [busy,setBusy]=useState(false), [notice,setNotice]=useState('');
  const [speechInterrupt,setSpeechInterrupt]=useState(false);
  const releaseAudio = () => {if(objectUrl.current){URL.revokeObjectURL(objectUrl.current);objectUrl.current=undefined;}};
  const stop = () => {if(audio.current){audio.current.pause();audio.current.currentTime=0;} releaseAudio();setNotice('已停止网页朗读。');};
  useEffect(() => () => {audio.current?.pause();releaseAudio();stream.current?.getTracks().forEach(track=>track.stop());cancelAnimationFrame(frame.current);}, []);
  async function ensureMicrophone() {
    if (stream.current) return stream.current;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前浏览器不支持麦克风打断测试。');
    stream.current=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    return stream.current;
  }
  async function monitor() {
    const media=await ensureMicrophone(); const context=new AudioContext();
    const analyser=context.createAnalyser(); analyser.fftSize=1024;
    context.createMediaStreamSource(media).connect(analyser); const values=new Uint8Array(analyser.fftSize);
    let loudFrames=0;
    const tick=()=>{if(!audio.current||audio.current.paused){void context.close();return;}
      analyser.getByteTimeDomainData(values); let energy=0;
      for(const value of values){const centered=(value-128)/128;energy+=centered*centered;}
      const rms=Math.sqrt(energy/values.length); loudFrames=rms>0.07?loudFrames+1:0;
      if(loudFrames>=4){stop();setNotice('检测到你说话，已打断网页朗读。');void context.close();return;}
      frame.current=requestAnimationFrame(tick);}; tick();
  }
  async function play(){if(busy)return;setBusy(true);setNotice('正在生成朗读…');try{
    const blob=await api.speech(text);audio.current?.pause();releaseAudio();const url=URL.createObjectURL(blob);objectUrl.current=url;
    const element=new Audio(url);audio.current=element;element.onended=()=>{releaseAudio();setNotice('朗读完成。');};
    element.onerror=()=>{releaseAudio();setNotice('浏览器无法播放生成的音频。');};
    await element.play();setNotice('正在电脑播放；这不会驱动圆屏。');if(speechInterrupt)void monitor().catch(e=>setNotice(String(e)));
  }catch(e){setNotice(e instanceof Error?e.message:'朗读失败。');}finally{setBusy(false);}}
  return <div className="speech-player"><Space wrap><Button size="small" loading={busy} onClick={()=>void play()}>网页朗读</Button><Button size="small" onClick={stop}>停止</Button><span>说话打断</span><Switch size="small" checked={speechInterrupt} onChange={async value=>{if(value){try{await ensureMicrophone();setNotice('麦克风只在浏览器本地检测音量，不上传录音。');}catch(e){setNotice(String(e));return;}}setSpeechInterrupt(value);}}/></Space>{notice&&<small role="status">{notice}</small>}</div>;
}
