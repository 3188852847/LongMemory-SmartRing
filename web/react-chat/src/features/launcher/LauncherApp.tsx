import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Checkbox, Drawer, Input, Modal, Segmented, Select, Switch} from 'antd';
import {OrbitMark, SciFiSurface, StatusIndicator} from '../../components/SciFiSurface';
import {AmbientMotionToggle} from '../../components/DigitalAtmosphere';
import {StateCore} from '../../components/StateCore';
import {TransitionSurface} from '../../components/TransitionSurface';
import {LauncherApi, LauncherError, type LauncherAction, type LauncherSettings, type LauncherSnapshot} from './api';

const stateText = {stopped: '等待开启', starting: '正在连接', ready: '服务已就绪', stopping: '正在停止', failed: '需要处理'};
const stateTone = {stopped: 'quiet', starting: 'busy', ready: 'good', stopping: 'busy', failed: 'bad'} as const;
const models = [{value: 'official', label: '官方 DeepSeek'}, {value: 'campus', label: '学校模型'}];
const fields: Array<{key: keyof LauncherSettings; label: string; options: Array<{value: string; label: string}>}> = [
  {key: 'model_profile', label: '文字模型', options: models},
  {key: 'voice_model_profile', label: '圆屏模型', options: models},
  {key: 'memory_extraction', label: '记忆提取', options: [{value: 'llm', label: '模型辅助提取'}, {value: 'rules', label: '规则提取'}]},
  {key: 'memory_retrieval', label: '记忆召回', options: [{value: 'hybrid', label: '关键词 + BGE 混合召回'}, {value: 'keyword', label: '关键词召回'}]},
  {key: 'memory_backend', label: '记忆系统', options: [{value: 'longmemory', label: '智慧圆屏长期记忆'}, {value: 'xiaozhi_local', label: '小智本地记忆'}, {value: 'none', label: '不启用记忆'}]},
  {key: 'voice_mode', label: '语音链路', options: [{value: 'pipeline', label: '本地语音链路'}, {value: 'doubao_realtime', label: '豆包实时语音（备用）'}]},
  {key: 'voice_latency_mode', label: '语音响应', options: [{value: 'realtime', label: '实时优先'}, {value: 'original', label: '原策略（对照）'}]},
  {key: 'vad_profile', label: '聆听环境', options: [{value: 'normal', label: '正常环境'}, {value: 'noisy', label: '嘈杂环境'}, {value: 'close_talk', label: '近距离说话'}]},
  {key: 'start_page', label: '进入网页时打开', options: [{value: 'chat', label: '文字聊天'}, {value: 'overview', label: '系统总览'}, {value: 'device', label: '设备状态'}, {value: 'memories', label: '记忆'}, {value: 'settings', label: '设置中心'}]},
];
const settingsGroups = [
  {value: 'daily', label: '常用', keys: ['model_profile', 'voice_model_profile']},
  {value: 'memory', label: '记忆', keys: ['memory_extraction', 'memory_retrieval', 'memory_backend']},
  {value: 'voice', label: '语音', keys: ['voice_mode', 'voice_latency_mode', 'vad_profile']},
  {value: 'display', label: '显示', keys: ['start_page']},
];

/** 面板只负责发出显式命令；轮询、打开设置、关闭页面都不会启动或停止服务。 */
export function LauncherApp({api, pollMs = 1200}: {api: LauncherApi; pollMs?: number}) {
  const [snapshot, setSnapshot] = useState<LauncherSnapshot | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsGroup, setSettingsGroup] = useState('daily');
  const [draft, setDraft] = useState<LauncherSettings | null>(null);
  const [revision, setRevision] = useState('');
  const [confirmation, setConfirmation] = useState<LauncherAction | null>(null);
  const [closed, setClosed] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const mounted = useRef(true);
  const operation = useRef(false);
  const generation = useRef(0);
  const originalSettings = useRef<LauncherSettings | null>(null);
  const mutationError = useRef(false);

  useEffect(() => {
    mounted.current = true;
    if (closed) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    async function poll() {
      // 非重叠轮询；写入期间不让旧 GET 覆盖刚收到的操作状态。
      if (!operation.current) {
        const before = generation.current;
        try {
          const next = await api.request('status', undefined, abort.signal);
          if (active && !operation.current && before === generation.current) {setSnapshot(next); if (!mutationError.current) setError('');}
        } catch (cause) {
          if (active && !operation.current) setError(cause instanceof LauncherError ? cause.message : '无法连接启动面板，请重新打开启动入口。');
          if (cause instanceof LauncherError && [401, 403].includes(cause.status)) return;
        }
      }
      if (active) timer = setTimeout(poll, pollMs);
    }
    void poll();
    return () => {active = false; mounted.current = false; clearTimeout(timer); abort.abort();};
  }, [api, pollMs, closed, refreshKey]);

  async function mutate(path: 'settings' | 'actions', body: unknown) {
    if (operation.current) return;
    generation.current += 1; operation.current = true; mutationError.current = false; setPending(true); setError('');
    try {
      const next = await api.request(path, body);
      if (mounted.current) setSnapshot(next);
      return next;
    } catch (cause) {
      mutationError.current = true;
      if (mounted.current) setError(cause instanceof LauncherError ? cause.message : '操作未完成，请检查服务状态后重试。');
    } finally {
      operation.current = false;
      if (mounted.current) setPending(false);
    }
  }
  async function action(value: LauncherAction) {
    const next = await mutate('actions', {action: value});
    if (next && value === 'shutdown') {setExiting(true); if (next.shutdown_complete) setClosed(true);}
    if (next) setConfirmation(null);
  }
  function openSettings() {
    if (!snapshot) return;
    originalSettings.current = {...snapshot.settings};
    setDraft({...snapshot.settings}); setRevision(snapshot.settings_revision); setSettingsGroup('daily'); setSettingsOpen(true);
  }
  async function saveSettings() {
    if (!snapshot || !draft) return;
    const changed = Object.fromEntries(Object.entries(draft).filter(([key, value]) => value !== originalSettings.current?.[key as keyof LauncherSettings]));
    if (!Object.keys(changed).length) {setSettingsOpen(false); return;}
    if (await mutate('settings', {settings: changed, expected_revision: revision})) setSettingsOpen(false);
  }
  const busy = pending || exiting || snapshot?.state === 'starting' || snapshot?.state === 'stopping';
  const settingsLocked = busy || snapshot?.state === 'ready';
  const tone = snapshot ? stateTone[snapshot.state] : 'quiet';
  const needsConsent = draft?.model_profile === 'campus' || (draft?.voice && draft.voice_mode === 'pipeline' && draft.voice_model_profile === 'campus');
  const coreState = closed ? 'stopped' : exiting ? 'stopping' : snapshot?.state ?? 'unknown';

  useEffect(() => {
    if (exiting && snapshot?.shutdown_complete) setClosed(true);
    if (exiting && snapshot?.state === 'failed') setExiting(false);
  }, [exiting, snapshot]);

  return <div className="launcher-root">
    <a className="skip-link" href="#launcher-main">跳到主要内容</a>
    <header className="launcher-header">
      <div className="launcher-brand"><OrbitMark/><span><strong>智慧圆屏</strong><small>你的陪伴，从这里开始</small></span></div>
      <div className="launcher-header-actions"><AmbientMotionToggle/><Button type="text" className="launcher-settings-trigger" onClick={openSettings} disabled={!snapshot || pending || closed}>启动设置 <span aria-hidden="true">↗</span></Button></div>
    </header>
    <main id="launcher-main" className="launcher-main">
      <section className="launcher-copy">
        <StatusIndicator tone={tone}>{closed ? '面板已退出' : exiting ? '正在停止并退出' : snapshot ? stateText[snapshot.state] : '连接启动面板'}</StatusIndicator>
        <h1>让记忆，<br/>陪你继续。</h1>
        <p className="launcher-intro">每一次交谈，都可以接着上一次。<br/>选择今天的交流方式，开启你的个人陪伴空间。</p>
        <fieldset className="launcher-mode" disabled={!snapshot || settingsLocked || closed}>
          <legend>交流方式</legend>
          <div className="launcher-mode-options">
            <button type="button" aria-pressed={snapshot?.settings.voice === false} onClick={() => void mutate('settings', {settings: {voice: false}, expected_revision: snapshot?.settings_revision})}>
              <span aria-hidden="true"><svg className="launcher-mode-icon" viewBox="0 0 24 24" fill="none"><rect x="3" y="5" width="18" height="12" rx="3" stroke="currentColor" strokeWidth="1.4"/><path d="M7 9h2m3 0h2m3 0h1M7 13h10M9 20h6" stroke="currentColor" strokeWidth="1.4"/></svg></span><strong>文字聊天</strong><small>在电脑上继续对话</small>
            </button>
            <button type="button" aria-pressed={snapshot?.settings.voice === true} onClick={() => void mutate('settings', {settings: {voice: true}, expected_revision: snapshot?.settings_revision})}>
              <span aria-hidden="true"><svg className="launcher-mode-icon" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.4"/><path d="M8 10v3m8-3v3m-7 3h6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg></span><strong>圆屏陪伴</strong><small>用声音连接智能圆屏</small>
            </button>
          </div>
        </fieldset>
        {snapshot && <p className="launcher-config-summary">{snapshot.settings.memory_retrieval === 'hybrid' ? '混合记忆召回' : '关键词记忆召回'}<span> / </span>{snapshot.settings.model_profile === 'official' ? '官方模型' : '学校模型'}{snapshot.settings.voice && <> / {snapshot.settings.tts_backend === 'cosyvoice3' ? 'CosyVoice 3' : '已保存的声音引擎'}</>}</p>}
      </section>
      <section className={`launcher-control state-${snapshot?.state ?? 'unknown'}`} aria-label="服务控制">
        <StateCore state={coreState}/>
        <p className="launcher-state" aria-live="polite">{closed ? '服务已停止，面板已退出' : snapshot ? stateText[snapshot.state] : '正在读取本机状态'}</p>
        <p className="launcher-state-detail">{closed ? '下次双击启动入口即可回来。' : snapshot?.message || '仅检查状态，不会自动启动服务。'}</p>
        <div className="launcher-primary-actions">
          {snapshot?.state === 'ready' ? <><Button type="primary" size="large" disabled={busy || closed || !snapshot.console_url} onClick={() => void action('open_console')}>进入陪伴空间 <span aria-hidden="true">↗</span></Button>
            <Button type="text" disabled={!snapshot.can_stop || busy || closed} onClick={() => setConfirmation('stop')}>停止服务</Button></>
            : snapshot?.state === 'failed' && snapshot.can_stop ? <Button type="primary" size="large" aria-label="重试停止" disabled={busy || closed} onClick={() => setConfirmation('stop')}>重试停止</Button>
            : <Button type="primary" size="large" aria-label={snapshot?.state === 'failed' ? '重新启动' : '开启陪伴'} disabled={!snapshot?.can_start || busy || closed || Boolean(error)} onClick={() => void action('start')} loading={snapshot?.state === 'starting' || pending}>{snapshot?.state === 'failed' ? '重新启动' : '开启陪伴'}</Button>}
        </div>
      </section>
      {error && <Alert className="launcher-error" type="error" title="需要处理" description={error} showIcon action={<Button disabled={pending || closed} onClick={() => setRefreshKey(value => value + 1)}>刷新状态</Button>}/>}
      <SciFiSurface className="launcher-services">
        <div className="launcher-services-heading"><h2>连接状态</h2><span>来自本机服务</span></div>
        <ul>{snapshot?.services.map(service => <li key={service.id}><span className="service-label">{service.label}</span><StatusIndicator tone={service.tone === 'idle' ? 'quiet' : service.tone === 'error' ? 'bad' : service.tone ?? 'quiet'}>{service.state}</StatusIndicator></li>) ?? <li><span className="service-label">本机启动服务</span><StatusIndicator>正在检查</StatusIndicator></li>}</ul>
      </SciFiSurface>
    </main>
    <footer className="launcher-footer"><span>关闭此页面，服务仍会继续运行。</span><Button type="text" disabled={!snapshot || busy || closed} onClick={() => setConfirmation('shutdown')}>停止服务并退出面板</Button></footer>
    <Drawer title="启动设置" open={settingsOpen} onClose={() => setSettingsOpen(false)} size={480} className="launcher-drawer"
      footer={<div className="launcher-drawer-footer"><span>保存后，下次启动生效</span><Button type="primary" onClick={() => void saveSettings()} disabled={settingsLocked || pending || Boolean(needsConsent && !draft?.http_risk_ack)}>保存设置</Button></div>}>
      {settingsLocked && <Alert type="info" title="请先停止服务，再修改启动设置。" showIcon/>}
      {error && <Alert type="error" title={error} showIcon action={error.includes('其他页面') ? <Button onClick={openSettings}>载入最新设置</Button> : undefined}/>}
      <Segmented className="launcher-settings-tabs" block aria-label="启动设置分类" options={settingsGroups.map(({value, label}) => ({value, label}))} value={settingsGroup} onChange={value => setSettingsGroup(String(value))}/>
      {draft && <div className="launcher-settings-form">
        <TransitionSurface identity={settingsGroup}>
          {settingsGroup === 'daily' && <div className="launcher-switch-row"><label htmlFor="launcher-voice">连接圆屏语音</label><Switch id="launcher-voice" checked={draft.voice} disabled={settingsLocked} onChange={voice => setDraft({...draft, voice})}/></div>}
          {fields.filter(field => settingsGroups.find(group => group.value === settingsGroup)?.keys.includes(field.key)).map(field => <div className="launcher-field" key={field.key}><label htmlFor={`launcher-${field.key}`}>{field.label}</label><Select id={`launcher-${field.key}`} options={field.options} value={String(draft[field.key])} disabled={settingsLocked} onChange={value => setDraft({...draft, [field.key]: value})}/></div>)}
          {settingsGroup === 'daily' && <div className="launcher-field"><label htmlFor="launcher-ip">电脑局域网 IP</label><Input id="launcher-ip" value={draft.lan_ip} placeholder="填写圆屏可访问的电脑 IPv4 地址" maxLength={64} disabled={settingsLocked} onChange={event => setDraft({...draft, lan_ip: event.target.value})}/></div>}
          {settingsGroup === 'voice' && <div className="launcher-engine"><span>当前声音引擎</span><strong>{draft.tts_backend === 'cosyvoice3' ? 'CosyVoice 3' : draft.tts_backend}</strong><p>声音与助手表达的详细选项，请进入陪伴空间查看。</p></div>}
          {settingsGroup === 'display' && <><div className="launcher-switch-row"><span>持续光效</span><AmbientMotionToggle/></div><p className="launcher-config-summary">光效立即改变当前浏览器，不需要保存，也不会启停服务。减少动画设置始终优先。</p></>}
        </TransitionSurface>
        {needsConsent && <div className="launcher-risk"><p>学校模型接口使用 HTTP，传输内容可能被网络中间方读取。请确认网络环境及数据使用范围。</p><Checkbox disabled={settingsLocked} checked={draft.http_risk_ack} onChange={event => setDraft({...draft, http_risk_ack: event.target.checked})}>我了解并接受本次使用的传输风险</Checkbox></div>}
      </div>}
    </Drawer>
    <Modal title={confirmation === 'shutdown' ? '停止服务并退出面板？' : '停止陪伴服务？'} open={confirmation !== null} okText={confirmation === 'shutdown' ? '停止并退出' : '停止服务'} cancelText="继续运行" okButtonProps={{danger: true}} confirmLoading={pending} onCancel={() => !pending && setConfirmation(null)} onOk={() => confirmation && void action(confirmation)}>
      <p>文字聊天和圆屏语音会断开，已保存的记忆会保留。{confirmation === 'shutdown' && '再次使用时，双击启动入口重新打开。'}</p>
    </Modal>
  </div>;
}
