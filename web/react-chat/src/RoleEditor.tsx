import {useRef, useState} from 'react';
import {Button, Collapse, Input, Modal, Select, Space, Switch} from 'antd';
import {ChatApi} from './api';
import {DeviceRoleSync} from './DeviceRoleSync';
import {applyRolePreferences, DEFAULT_ROLE_PREFERENCES, readRolePreferences, type RolePreferences} from './rolePreferences';
import {settingsFailure} from './settingsFailure';

interface Role {revision: number; name: string; prompt: string; saved_at: string | null}
interface Settings {current: Role; presets: {name: string; prompt: string}[]; web: string; device: string}

export function RoleEditor({api, disabled, onSaved}: {api: ChatApi; disabled: boolean; onSaved: () => void}) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings>();
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [guided, setGuided] = useState(false);
  const [preferences, setPreferences] = useState<RolePreferences>({...DEFAULT_ROLE_PREFERENCES});
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  async function load() {
    if (lock.current) return; lock.current = true; setBusy(true);
    try {
      const data = await api.request<Settings>('/api/assistant-role');
      const structured = readRolePreferences(data.current.prompt);
      setSettings(data); setName(data.current.name); setPrompt(data.current.prompt);
      setGuided(structured.enabled); setPreferences(structured.preferences); setUnknown(false);
      setNotice('已读取当前版本。编辑内容只有点击保存后才生效。');
    } catch (error) {setNotice(settingsFailure(error, 'read'));} finally {lock.current = false; setBusy(false);}
  }
  async function save() {
    if (lock.current || !settings || unknown) return;
    const savedPrompt = applyRolePreferences(prompt, preferences, guided);
    if (savedPrompt.length > 12000) {
      setNotice('完整提示词加上结构化偏好后超过 12000 字符，请缩短高级提示词后再保存。');
      return;
    }
    lock.current = true; setBusy(true);
    try {
      const result = await api.request<Omit<Settings, 'presets'>>('/api/assistant-role', 'POST', {expected_revision: settings.current.revision, name, prompt:savedPrompt});
      setSettings({...settings, ...result}); setName(result.current.name); setPrompt(result.current.prompt);
      setNotice(`已保存版本 ${result.current.revision}。网页下一轮使用；正在回答的轮次不变。未自动同步圆屏，请在下方检查。`); onSaved();
    } catch (error) {setUnknown(true); setNotice(`${settingsFailure(error, 'write')} 草稿仍保留在编辑框。`);}
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
      <p>网页：{settings?.web === 'fake_no_persona' ? 'Fake 仅保存配置，不模拟人格' : '保存后下一轮使用'}。圆屏：需单独检查与同步，运行生效不自动确认。</p>
      <p>当前保存版本：{settings?.current.revision ?? '未读取'} · {settings?.current.name ?? ''}</p>
      <label>载入预设（只填入草稿）</label><Select className="wide" aria-label="载入角色预设" placeholder="选择预设" value={null} disabled={busy || !settings} options={settings?.presets.map(p => ({value:p.name,label:p.name}))}
        onChange={value => {const preset = settings?.presets.find(p => p.name === value); if (preset) {setName(preset.name); setPrompt(preset.prompt); setGuided(false); setPreferences({...DEFAULT_ROLE_PREFERENCES});}}}/>
      <label htmlFor="role-name">角色名称</label><Input id="role-name" value={name} maxLength={60} disabled={busy || !settings} onChange={e => setName(e.target.value)}/>
      <div className="role-guided-settings">
        <Space className="setting-line" wrap><div><strong>结构化表达偏好</strong><p>用常用选项调整表达；关闭后保存会移除这一受管配置，不改其他提示词。</p></div><Switch aria-label="启用结构化表达偏好" checked={guided} disabled={busy || !settings} onChange={setGuided}/></Space>
        <fieldset disabled={!guided || busy || !settings}>
          <label htmlFor="user-address">希望助手怎么称呼你（可留空）</label><Input id="user-address" value={preferences.userAddress} maxLength={20} placeholder="例如：小林" onChange={event => setPreferences({...preferences,userAddress:event.target.value.replace(/[\r\n\u0000【】]/g,'')})}/>
          <div className="role-preference-grid">
            <div><label>回答长度</label><Select aria-label="回答长度" value={preferences.responseLength} onChange={value=>setPreferences({...preferences,responseLength:value})} options={[{value:'brief',label:'简短陪聊'},{value:'balanced',label:'自然平衡'},{value:'detailed',label:'需要时详细'}]}/></div>
            <div><label>互动方式</label><Select aria-label="互动方式" value={preferences.interactionStyle} onChange={value=>setPreferences({...preferences,interactionStyle:value})} options={[{value:'listen_first',label:'倾听为主'},{value:'ask_before_advice',label:'先倾听，再问是否需要建议'},{value:'direct',label:'直接分析和解决'}]}/></div>
            <div><label>表情频率</label><Select aria-label="表情频率" value={preferences.emojiFrequency} onChange={value=>setPreferences({...preferences,emojiFrequency:value})} options={[{value:'none',label:'不使用'},{value:'occasional',label:'偶尔使用'},{value:'natural',label:'轻松聊天时自然使用'}]}/></div>
          </div>
          <Button size="small" onClick={() => setPreferences({...DEFAULT_ROLE_PREFERENCES})}>恢复推荐表达草稿</Button>
        </fieldset>
      </div>
      <Collapse className="role-advanced" items={[{key:'prompt',label:'高级：编辑完整角色提示词',children:<><p>结构化偏好会在保存时写入独立受管区块；其余手写内容保持原样。</p><label htmlFor="role-prompt">角色提示词</label><Input.TextArea id="role-prompt" value={prompt} rows={10} maxLength={12000} disabled={busy || !settings} onChange={e => setPrompt(e.target.value)}/></>}]} />
      <p>基础记忆证据约束仍保留；旧聊天上下文可能延续原风格，可新建聊天体验。</p>
      <Button type="primary" disabled={busy || unknown || !settings || !name.trim() || !prompt.trim()} onClick={() => void save()}>保存并用于网页下一轮</Button>{' '}
      <Button disabled={busy} onClick={() => {if (confirm('重新读取会替换当前草稿，继续吗？')) void load();}}>重新读取</Button>
      <p role="status">{notice}</p>
      <DeviceRoleSync key={settings?.current.revision ?? -1} api={api} disabled={busy || unknown || !settings}/>
    </Modal></>;
}
