import {useRef, useState} from 'react';
import {Button, Input, Modal, Select} from 'antd';
import {ChatApi} from './api';

interface Role {revision: number; name: string; prompt: string; saved_at: string | null}
interface Settings {current: Role; presets: {name: string; prompt: string}[]; web: string; device: string}

export function RoleEditor({api, disabled, onSaved}: {api: ChatApi; disabled: boolean; onSaved: () => void}) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings>();
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  async function load() {
    if (lock.current) return; lock.current = true; setBusy(true);
    try {
      const data = await api.request<Settings>('/api/assistant-role');
      setSettings(data); setName(data.current.name); setPrompt(data.current.prompt); setUnknown(false);
      setNotice('已读取当前版本。编辑内容只有点击保存后才生效。');
    } catch (error) {setNotice(String(error));} finally {lock.current = false; setBusy(false);}
  }
  async function save() {
    if (lock.current || !settings || unknown) return; lock.current = true; setBusy(true);
    try {
      const result = await api.request<Omit<Settings, 'presets'>>('/api/assistant-role', 'POST', {expected_revision: settings.current.revision, name, prompt});
      setSettings({...settings, ...result}); setName(result.current.name); setPrompt(result.current.prompt);
      setNotice(`已保存版本 ${result.current.revision}。网页下一轮使用；正在回答的轮次不变。圆屏未同步。`); onSaved();
    } catch (error) {setUnknown(true); setNotice(`${String(error)} 请先重新读取，勿重复保存；草稿仍保留在编辑框。`);}
    finally {lock.current = false; setBusy(false);}
  }
  function close() {
    if (busy) return;
    if (settings && (name !== settings.current.name || prompt !== settings.current.prompt) && !confirm('关闭会丢弃未保存的草稿，继续吗？')) return;
    setOpen(false);
  }
  return <><Button disabled={disabled} onClick={() => {setOpen(true); void load();}}>助手角色设置</Button>
    <Modal title="助手角色设置" open={open} onCancel={close} footer={null} width={720}>
      <p>这是助手的表达方式，不是你的个人画像。不要在这里填写密码或密钥。</p>
      <p>网页：{settings?.web === 'fake_no_persona' ? 'Fake 仅保存配置，不模拟人格' : '保存后下一轮使用'}。圆屏：未同步，仍使用小智配置。</p>
      <p>当前保存版本：{settings?.current.revision ?? '未读取'} · {settings?.current.name ?? ''}</p>
      <label>载入预设（只填入草稿）</label><Select className="wide" aria-label="载入角色预设" placeholder="选择预设" value={null} disabled={busy || !settings} options={settings?.presets.map(p => ({value:p.name,label:p.name}))}
        onChange={value => {const preset = settings?.presets.find(p => p.name === value); if (preset) {setName(preset.name); setPrompt(preset.prompt);}}}/>
      <label htmlFor="role-name">角色名称</label><Input id="role-name" value={name} maxLength={60} disabled={busy || !settings} onChange={e => setName(e.target.value)}/>
      <label htmlFor="role-prompt">角色提示词</label><Input.TextArea id="role-prompt" value={prompt} rows={10} maxLength={12000} disabled={busy || !settings} onChange={e => setPrompt(e.target.value)}/>
      <p>基础记忆证据约束仍保留；旧聊天上下文可能延续原风格，可新建聊天体验。</p>
      <Button type="primary" disabled={busy || unknown || !settings || !name.trim() || !prompt.trim()} onClick={() => void save()}>保存并用于网页下一轮</Button>{' '}
      <Button disabled={busy} onClick={() => {if (confirm('重新读取会替换当前草稿，继续吗？')) void load();}}>重新读取</Button>
      <p role="status">{notice}</p>
    </Modal></>;
}
