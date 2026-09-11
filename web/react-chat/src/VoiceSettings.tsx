import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Input, Modal, Select, Slider, Space} from 'antd';
import {ApiError, ChatApi} from './api';
import {SpeechPlayer} from './SpeechPlayer';

type VoxProfile={version:number;reference:string|null;style:string;cfg_value:number;quality:'fast'|'balanced'|'quality'};

interface Settings {
  backend: 'edge' | 'voxcpm2' | 'sanotts' | 'unsupported'; voice: string | null; voices: string[];
  digest: string; text: string; config_matches: boolean; editable: boolean; service_ready?: boolean | null;
  profile?:VoxProfile; profile_digest?:string; references?:Array<{id:string|null;label:string}>;
  speed?: number;
}

export function voiceSettingsFailure(error: unknown) {
  if (!(error instanceof ApiError)) return '声音操作未完成。请确认本机控制台仍在运行，再重新读取配置。';
  const messages: Record<string, string> = {
    voice_not_enabled: '当前控制台没有启用小智声音配置。请从统一启动面板启动圆屏语音后再读取。',
    voice_operation_failed_recheck: '声音配置读取、试听或保存没有完成。请先重新读取配置，不要连续重试。',
    session_required: '网页会话已经失效。请刷新整个页面；没有自动重发声音操作。',
    csrf_rejected: '请求校验失败。请刷新整个页面；没有自动重发声音操作。',
  };
  return messages[error.code] ?? '声音操作未完成。请重新读取配置，不要根据旧页面判断是否已经生效。';
}

export function VoiceSettings({api, disabled}: {api: ChatApi; disabled: boolean}) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Settings>(), [voice, setVoice] = useState('');
  const [profile,setProfile]=useState<VoxProfile>();
  const [sanoSpeed,setSanoSpeed]=useState(1);
  const [notice, setNotice] = useState(''), [audio, setAudio] = useState('');
  const lock = useRef(false), audioRef = useRef('');
  const clearAudio = () => {if (audioRef.current) URL.revokeObjectURL(audioRef.current); audioRef.current = ''; setAudio('');};
  useEffect(() => () => {if (audioRef.current) URL.revokeObjectURL(audioRef.current);}, []);
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setNotice('');
    try {await action();} catch (e) {setNotice(voiceSettingsFailure(e));}
    finally {lock.current = false; setBusy(false);}
  }
  const load = () => run(async () => {setSettings(undefined); const value = await api.request<Settings>('/api/voice-settings'); setSettings(value); setVoice(value.voice ?? '');setProfile(value.profile);setSanoSpeed(value.speed ?? 1);});
  return <><Button disabled={disabled} onClick={() => {setOpen(true); void load();}}>声音设置</Button>
    <Modal title="声音设置" open={open} footer={null} closable={!busy} maskClosable={!busy} onCancel={() => {clearAudio(); setOpen(false);}}>
      <Space orientation="vertical" style={{width: '100%'}}>
        {notice && <Alert type="warning" title={notice}/>}
        {!settings && <Alert type="info" title="正在读取小智声音配置…"/>}
        {settings?.backend === 'voxcpm2' && <>
          <Alert type={settings.config_matches && settings.service_ready ? 'success' : 'warning'}
            title={settings.config_matches ? '当前配置：VoxCPM2 本地声音' : 'VoxCPM2 配置与本机适配契约不一致'}
            description={settings.service_ready ? '本机模型服务已就绪；圆屏是否正在播放仍以实际试听为准。' : '本机模型服务未就绪。请通过统一启动面板选择 VoxCPM2 后启动。'}/>
          {profile&&<>
            <label>参考音色</label><Select aria-label="参考音色" className="wide" value={profile.reference??'__default__'} options={(settings.references??[]).map(item=>({value:item.id??'__default__',label:item.label}))} onChange={reference=>setProfile({...profile,reference:reference==='__default__'?null:reference})}/>
            <small>参考 WAV 决定说话人音色；“模型默认声线”不做克隆。当前只列出本机受控音频目录。</small>
            <label>表达指令</label><Input maxLength={100} value={profile.style} placeholder="例如：年轻女性，声音温柔明亮，语速自然，带着微笑" onChange={event=>setProfile({...profile,style:event.target.value})}/>
            <label>指令强度：{profile.cfg_value.toFixed(1)}</label><Slider min={1} max={3} step={0.1} value={profile.cfg_value} onChange={cfg_value=>setProfile({...profile,cfg_value})}/>
            <label>生成质量</label><Select className="wide" value={profile.quality} options={[{value:'fast',label:'快速（6 步）'},{value:'balanced',label:'均衡（10 步）'},{value:'quality',label:'细致（20 步，更慢）'}]} onChange={quality=>setProfile({...profile,quality})}/>
            <Space wrap><Button onClick={() => {clearAudio();setProfile({...profile,reference:null,style:'',cfg_value:2,quality:'balanced'});setNotice('已恢复 VoxCPM2 推荐值草稿；点击保存后才会生效。');}}>恢复推荐声音草稿</Button>
            <Button type="primary" disabled={busy||!settings.service_ready} onClick={()=>void run(async()=>{
              const value=await api.request<{profile:VoxProfile;profile_digest:string;references:Settings['references']}>('/api/voice-settings','POST',{...profile,expected_profile_digest:settings.profile_digest});
              setProfile(value.profile);setSettings({...settings,profile:value.profile,profile_digest:value.profile_digest,references:value.references});setNotice('声音方案已保存，网页和圆屏下一次合成时使用。');
            })}>保存声音方案</Button></Space>
            <p>测试文本：{settings.text}</p><SpeechPlayer api={api} text={settings.text}/>
          </>}
        </>}
        {settings?.backend === 'sanotts' && <>
          <Alert type={settings.config_matches && settings.service_ready ? 'success' : 'warning'}
            title={settings.config_matches ? '当前配置：sanoTTS 本地中文小雅' : 'sanoTTS 配置与本机适配契约不一致'}
            description={settings.service_ready
              ? '本机 WASM 服务已就绪；当前仍是整段 WAV 生成，不代表已经实现流式首声或中途取消。'
               : '本机服务未就绪。请在统一启动面板选择 sanoTTS，并核对外部源码目录。'}/>
          <label>说话速度：{sanoSpeed.toFixed(2)}×</label>
          <Slider aria-label="sanoTTS 说话速度" min={0.75} max={1.5} step={0.05} value={sanoSpeed}
            disabled={busy || !settings.editable} onChange={setSanoSpeed}/>
          <small>只改变 sanoTTS 的朗读速度，不改变模型、角色、记忆或圆屏扬声器音量。</small>
          <Space wrap>
            <Button disabled={busy} onClick={()=>{setSanoSpeed(1);setNotice('已恢复标准语速草稿；点击保存后才会生效。');}}>恢复标准语速草稿</Button>
            <Button type="primary" disabled={busy || !settings.service_ready || sanoSpeed === settings.speed} onClick={()=>void run(async()=>{
              const value=await api.request<Settings>('/api/voice-settings','POST',{speed:sanoSpeed,expected_digest:settings.digest});
              setSettings({...settings,...value,service_ready:settings.service_ready});setSanoSpeed(value.speed ?? sanoSpeed);
              setNotice('sanoTTS 语速已保存；网页朗读立即使用，圆屏语音重启后使用。');
            })}>保存说话速度</Button>
          </Space>
          <p>测试文本：{settings.text}</p>
          <SpeechPlayer api={api} text={settings.text}/>
        </>}
        {settings?.backend === 'unsupported' && <Alert type="warning" title="当前 TTS 配置不受本控制台支持" description="请在统一启动面板重新选择并同步 EdgeTTS、VoxCPM2 或 sanoTTS。"/>}
        {settings?.backend === 'edge' && <>
          <Alert type="info" title="试听会联网发送下方固定文本，不发送聊天记录。在电脑播放，不代表圆屏音量。保存后请重启小智。"/>
          <p>当前配置：EdgeTTS · {settings.voice}（不代表运行中的音色）</p>
          <Select aria-label="选择音色" style={{width: '100%'}} value={voice || undefined} disabled={busy || !settings.editable}
            options={settings.voices.map(value => ({value, label: value}))} onChange={value => {clearAudio(); setVoice(value);}}/>
          <p>试听文本：{settings.text}</p>
          <Button disabled={busy || !settings.voices.includes(voice)} onClick={() => void run(async () => {
            clearAudio(); const blob = await api.voicePreview(voice); audioRef.current = URL.createObjectURL(blob); setAudio(audioRef.current);
          })}>联网生成试听</Button>
          {audio && <audio controls src={audio} aria-label="音色试听"/>}
          <Button type="primary" disabled={busy || !settings.voices.includes(voice) || voice === settings.voice} onClick={() => {
            if (!window.confirm('保存到小智配置并创建原配置备份？不会自动重启小智。')) return;
            void run(async () => {try {
              const value = await api.request<Settings>('/api/voice-settings', 'POST', {voice, expected_digest: settings.digest});
              setSettings(value); setNotice('已保存配置。请停止并重新启动小智，圆屏重新连接后生效。');
            } catch (error) {setSettings(undefined); throw error;}});
          }}>保存音色</Button>
        </>}
        <Button disabled={busy} onClick={() => void load()}>重新读取配置</Button>
      </Space>
    </Modal></>;
}
