import {useCallback, useEffect, useRef, useState} from 'react';
import {Button, Input, Select, Space, Switch} from 'antd';
import {ChatApi} from '../../api';
import {DeviceRoleSync} from './DeviceRoleSync';
import {applyRolePreferences, DEFAULT_ROLE_PREFERENCES, readRolePreferences, type RolePreferences} from './rolePreferences';
import {settingsFailure} from './settingsFailure';
import {useUnsavedChanges} from '../../app/UnsavedChanges';

interface Role {revision: number; name: string; prompt: string; saved_at: string | null}
interface Settings {current: Role; history?: Role[]; presets: {name: string; prompt: string}[]; web: string; device: string}

export function RoleEditor({api, disabled, onSaved}: {api: ChatApi; disabled: boolean; onSaved: () => void}) {
  const [settings, setSettings] = useState<Settings>();
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [guided, setGuided] = useState(false);
  const [preferences, setPreferences] = useState<RolePreferences>({...DEFAULT_ROLE_PREFERENCES});
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [notice, setNotice] = useState('');
  const savedPreferences = settings ? readRolePreferences(settings.current.prompt) : undefined;
  const dirty = Boolean(settings && (name !== settings.current.name || prompt !== settings.current.prompt
    || guided !== savedPreferences?.enabled
    || (guided && JSON.stringify(preferences) !== JSON.stringify(savedPreferences?.preferences))));
  useUnsavedChanges(dirty, '有未保存的助手表达草稿。');
  const lock = useRef(false);
  const load = useCallback(async () => {
    if (lock.current) return; lock.current = true; setBusy(true);
    try {
      const data = await api.request<Settings>('/api/assistant-role');
      const structured = readRolePreferences(data.current.prompt);
      setSettings(data); setName(data.current.name); setPrompt(data.current.prompt);
      setGuided(structured.enabled); setPreferences(structured.preferences); setUnknown(false);
      setNotice('');
    } catch (error) {setNotice(settingsFailure(error, 'read'));} finally {lock.current = false; setBusy(false);}
  }, [api]);
  useEffect(() => {if (!disabled) void load();}, [disabled, load]);
  async function save() {
    if (lock.current || !settings || unknown) return;
    const savedPrompt = applyRolePreferences(prompt, preferences, guided);
    if (savedPrompt.length > 12000) {
      setNotice('完整提示词加上结构化偏好后超过 12000 字符，请缩短人格卡后再保存。');
      return;
    }
    lock.current = true; setBusy(true);
    try {
      const result = await api.request<Omit<Settings, 'presets'>>('/api/assistant-role', 'POST', {expected_revision: settings.current.revision, name, prompt:savedPrompt});
      setSettings({...settings, ...result}); setName(result.current.name); setPrompt(result.current.prompt);
      const normalized = readRolePreferences(result.current.prompt);
      setGuided(normalized.enabled); setPreferences(normalized.preferences);
      setNotice(`已保存版本 ${result.current.revision}。网页下一轮使用；正在回答的轮次不变。未自动同步圆屏，请在下方检查。`); onSaved();
    } catch (error) {setUnknown(true); setNotice(`${settingsFailure(error, 'write')} 草稿仍保留在编辑框。`);}
    finally {lock.current = false; setBusy(false);}
  }
  return <section className="role-editor" aria-label="角色设置">
      <p>{settings?.web === 'fake_no_persona' ? '演示模式仅保存人格卡。' : '保存后，网页从下一轮聊天开始使用这张人格卡。'}</p>
      <label htmlFor="role-name">角色名称</label><Input id="role-name" value={name} maxLength={60} disabled={disabled || busy || !settings} onChange={e => setName(e.target.value)}/>
      <label htmlFor="role-prompt">人格卡</label>
      <Input.TextArea id="role-prompt" value={prompt} rows={9} maxLength={12000} disabled={disabled || busy || !settings} onChange={e => setPrompt(e.target.value)}/>
      <div>
      <Button type="primary" disabled={disabled || busy || unknown || !settings || !name.trim() || !prompt.trim()} onClick={() => void save()}>保存并用于网页下一轮</Button>{' '}
      <Button disabled={disabled || busy} onClick={() => {if (confirm('重新读取会替换当前草稿，继续吗？')) void load();}}>重新读取</Button>
      <p role="status">{notice}</p>
      </div>
      <details><summary>预设、历史与表达偏好</summary>
      <label>载入预设（只填入草稿）</label><Select className="wide" aria-label="载入角色预设" placeholder="选择预设" value={null} disabled={disabled || busy || !settings} options={settings?.presets?.map(p => ({value:p.name,label:p.name}))}
        onChange={value => {const preset = settings?.presets.find(p => p.name === value); if (preset) {setName(preset.name); setPrompt(preset.prompt); setGuided(false); setPreferences({...DEFAULT_ROLE_PREFERENCES});}}}/>
      <label>载入历史版本（只填入草稿）</label><Select className="wide" aria-label="载入角色历史版本" placeholder={settings?.history?.length ? '选择最近保存的版本' : '还没有已保存的历史版本'} value={null} disabled={disabled || busy || !settings?.history?.length}
        options={settings?.history?.map(role => ({value:role.revision,label:`修订 ${role.revision} · ${role.name}${role.revision === settings.current.revision ? '（当前）' : ''}`}))}
        onChange={revision => {const role = settings?.history?.find(item => item.revision === revision); if (role) {const structured = readRolePreferences(role.prompt); setName(role.name); setPrompt(role.prompt); setGuided(structured.enabled); setPreferences(structured.preferences); setNotice(`已将修订 ${role.revision} 载入草稿；点击保存后才会创建新版本并生效。`);}}}/>
      <div className="role-guided-settings">
        <Space className="setting-line" wrap><div><strong>结构化表达偏好</strong><p>用常用选项调整表达；关闭后保存会移除这一受管配置，不改其他提示词。</p></div><Switch aria-label="启用结构化表达偏好" checked={guided} disabled={disabled || busy || !settings} onChange={setGuided}/></Space>
        <fieldset disabled={disabled || !guided || busy || !settings}>
          <label htmlFor="user-address">希望助手怎么称呼你（可留空）</label><Input id="user-address" value={preferences.userAddress} maxLength={20} placeholder="例如：小林" onChange={event => setPreferences({...preferences,userAddress:event.target.value.replace(/[\r\n\u0000【】]/g,'')})}/>
          <div className="role-preference-grid">
            <div><label>回答长度</label><Select aria-label="回答长度" value={preferences.responseLength} onChange={value=>setPreferences({...preferences,responseLength:value})} options={[{value:'brief',label:'简短陪聊'},{value:'balanced',label:'自然平衡'},{value:'detailed',label:'需要时详细'}]}/></div>
            <div><label>互动方式</label><Select aria-label="互动方式" value={preferences.interactionStyle} onChange={value=>setPreferences({...preferences,interactionStyle:value})} options={[{value:'listen_first',label:'倾听为主'},{value:'ask_before_advice',label:'先倾听，再问是否需要建议'},{value:'direct',label:'直接分析和解决'}]}/></div>
            <div><label>表情频率</label><Select aria-label="表情频率" value={preferences.emojiFrequency} onChange={value=>setPreferences({...preferences,emojiFrequency:value})} options={[{value:'none',label:'不使用'},{value:'occasional',label:'偶尔使用'},{value:'natural',label:'轻松聊天时自然使用'}]}/></div>
          </div>
          <Button size="small" onClick={() => setPreferences({...DEFAULT_ROLE_PREFERENCES})}>恢复推荐表达草稿</Button>
        </fieldset>
      </div>
      </details>
      <DeviceRoleSync key={settings?.current.revision ?? -1} api={api} disabled={disabled || busy || unknown || !settings}/>
    </section>;
}
