import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Modal, Select, Space} from 'antd';
import {ChatApi} from './api';

interface Settings {voice: string; voices: string[]; digest: string; text: string}
export function VoiceSettings({api, disabled}: {api: ChatApi; disabled: boolean}) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Settings>(), [voice, setVoice] = useState('');
  const [notice, setNotice] = useState(''), [audio, setAudio] = useState('');
  const lock = useRef(false), audioRef = useRef('');
  const clearAudio = () => {if (audioRef.current) URL.revokeObjectURL(audioRef.current); audioRef.current = ''; setAudio('');};
  useEffect(() => () => {if (audioRef.current) URL.revokeObjectURL(audioRef.current);}, []);
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setNotice('');
    try {await action();} catch (e) {setNotice(e instanceof Error ? e.message : '操作失败，请重新读取。');}
    finally {lock.current = false; setBusy(false);}
  }
  const load = () => run(async () => {setSettings(undefined); const value = await api.request<Settings>('/api/voice-settings'); setSettings(value); setVoice(value.voice);});
  return <><Button disabled={disabled} onClick={() => {setOpen(true); void load();}}>声音设置</Button>
    <Modal title="声音设置 · Edge TTS" open={open} footer={null} closable={!busy} maskClosable={!busy} onCancel={() => {clearAudio(); setOpen(false);}}>
      <Space orientation="vertical" style={{width: '100%'}}>
        <Alert type="info" title="试听会联网发送下方固定文本，不发送聊天记录。在电脑播放，不代表圆屏音量。保存后请重启小智。"/>
        {notice && <Alert type="warning" title={notice}/>}
        <p>配置音色：{settings?.voice ?? '尚未读取'}（不代表运行中的音色）</p>
        <Select aria-label="选择音色" style={{width: '100%'}} value={voice || undefined} disabled={busy || !settings}
          options={settings?.voices.map(value => ({value, label: value}))} onChange={value => {clearAudio(); setVoice(value);}}/>
        <p>试听文本：{settings?.text}</p>
        <Button disabled={busy || !settings?.voices.includes(voice)} onClick={() => void run(async () => {
          clearAudio(); const blob = await api.voicePreview(voice); audioRef.current = URL.createObjectURL(blob); setAudio(audioRef.current);
        })}>联网生成试听</Button>
        {audio && <audio controls src={audio} aria-label="音色试听"/>}
        <Button type="primary" disabled={busy || !settings?.voices.includes(voice) || voice === settings.voice} onClick={() => {
          if (!settings || !window.confirm('保存到小智配置并创建原配置备份？不会自动重启小智。')) return;
          void run(async () => {try {
            const value = await api.request<Settings>('/api/voice-settings', 'POST', {voice, expected_digest: settings.digest});
            setSettings(value); setNotice('已保存配置。请停止并重新启动小智，圆屏重新连接后生效。');
          } catch (error) {setSettings(undefined); throw error;}});
        }}>保存音色</Button>
        <Button disabled={busy} onClick={() => void load()}>重新读取配置</Button>
      </Space>
    </Modal></>;
}
