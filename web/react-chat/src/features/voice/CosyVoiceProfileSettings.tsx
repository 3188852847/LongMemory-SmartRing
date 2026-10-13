import {useEffect, useRef, useState} from 'react';
import {Alert, Button, Input, Select, Space} from 'antd';
import {ApiError, type ChatApi} from '../../api';

export type CosyVoiceProfile = {version: 1; reference_id: string | null; transcript: string; style: string};
type Reference = {id: string; label: string; transcript: string; sha256: string; duration_seconds: number};
type Snapshot = {profile: CosyVoiceProfile; profile_digest: string; references: Reference[]; preview_text: string; service_state: 'ready' | 'needs_restart' | 'unavailable'; activation: 'next_synthesis' | 'after_service_start'};
const defaultProfile: CosyVoiceProfile = {version: 1, reference_id: null, transcript: '', style: ''};
const styles = ['自然平静地说话', '温柔亲切地说话', '开心地说话', '轻声地说话'];

function failure(error: unknown) {
  if (error instanceof ApiError && error.code === 'voice_profile_changed') return '声音档案已在其他页面修改。请重新读取后再保存；草稿仍保留。';
  if (error instanceof ApiError && error.code === 'invalid_voice_reference') return '参考音频未保存。请使用 3–30 秒、16–48 kHz、单声道或双声道的 PCM16 WAV，并填写对应原文。';
  if (error instanceof ApiError && error.code === 'voice_reference_library_full') return '参考库已达到 32 份录音上限。已有录音仍可选择，本次没有新增文件。';
  if (error instanceof ApiError && error.code === 'voice_profile_service_restart_required') return '声音服务尚未支持新档案，请从启动面板停止后重新启动服务，再重新读取声音档案。';
  if (error instanceof ApiError && ['voice_preview_unavailable', 'speech_busy'].includes(error.code)) return '试听未完成。请确认 CosyVoice 3 已启动，等待当前语音结束后再试听。';
  return '声音操作未完成。请重新读取配置，核对后再操作。';
}

async function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.readAsDataURL(file);
  });
}

/** 声音草稿、试听和保存是三个明确动作；试听不覆盖网页/圆屏当前声线。 */
export function CosyVoiceProfileSettings({api, disabled}: {api: ChatApi; disabled: boolean}) {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [draft, setDraft] = useState<CosyVoiceProfile>(defaultProfile);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(''), [error, setError] = useState('');
  const [file, setFile] = useState<File>(), [label, setLabel] = useState(''), [transcript, setTranscript] = useState('');
  const [audio, setAudio] = useState('');
  const [reloadRequested, setReloadRequested] = useState(false);
  const lock = useRef(false), mounted = useRef(true), audioRef = useRef('');
  const clearAudio = () => {if (audioRef.current) URL.revokeObjectURL(audioRef.current); audioRef.current = ''; setAudio(''); setNotice('');};
  useEffect(() => () => {mounted.current = false; if (audioRef.current) URL.revokeObjectURL(audioRef.current);}, []);
  async function run(operation: () => Promise<void>) {
    if (lock.current || disabled) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try {await operation();} catch (reason) {if (mounted.current) setError(failure(reason));}
    finally {lock.current = false; if (mounted.current) setBusy(false);}
  }
  async function load() {
    const next = await api.request<Snapshot>('/api/voice-profile');
    if (mounted.current) {setSnapshot(next); setDraft(next.profile); setReloadRequested(false); clearAudio();}
  }
  useEffect(() => {mounted.current = true; if (!disabled) void run(load);}, [api, disabled]);
  const locked = disabled || busy;
  const dirty = Boolean(snapshot && (draft.reference_id !== snapshot.profile.reference_id
    || draft.transcript !== snapshot.profile.transcript || draft.style !== snapshot.profile.style));
  // 离开页面提醒未保存的声线；分类切换仍保留已挂载的草稿。
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = '';};
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  return <section className="settings-subsection voice-profile-workspace" aria-labelledby="cosy-profile-title">
    <h3 id="cosy-profile-title">我的声音</h3>
    <p>参考录音决定声线，表达指令尝试语气，与助手性格分别保存。录音供本机 CosyVoice 3 使用，请使用本人或已获授权的声音。</p>
    <ol className="voice-workflow" aria-label="声音设置流程">
      <li>添加或选择参考录音</li><li>调整表达</li><li>试听草稿</li><li>保存日用声线</li><li>下次合成使用</li>
    </ol>
    <p role="status">{!snapshot ? busy ? '正在读取声音档案…' : '声音档案尚未读取' : dirty ? '有未保存的声音草稿；当前日用声线未改变。' : '当前草稿与已保存档案一致。'}</p>
    {error && <Alert type="warning" showIcon title={error}/>}
    {snapshot && snapshot.service_state !== 'ready' && <Alert type="info" title={snapshot.service_state === 'needs_restart' ? '需要重新启动声音服务' : '声音服务尚未就绪'} description="可以保存声音档案；从启动面板启动新版 CosyVoice 3 服务后生效，当前不能试听草稿。"/>}
    {notice && <Alert type="success" showIcon title={notice}/>}
    <div className="voice-profile-columns">
    <section className="voice-draft-fields" aria-label="声音草稿编辑">
      <h4>参考录音与表达</h4>
      <Space orientation="vertical" style={{width: '100%'}}>
      <details><summary>添加参考录音</summary><Space orientation="vertical" style={{width: '100%'}}>
        <p>PCM16 WAV，3–30 秒，16–48 kHz，最多 4 MiB。上传不会自动切换当前声线。</p>
        <label htmlFor="cosy-upload">参考录音文件</label><input id="cosy-upload" type="file" accept=".wav,audio/wav" disabled={locked} onChange={event => {const value = event.target.files?.[0]; setFile(value); if (value) setLabel(value.name.replace(/\.wav$/i, '').slice(0, 80));}}/>
        <label htmlFor="cosy-label">声线名称</label><Input id="cosy-label" maxLength={80} disabled={locked} value={label} onChange={event => setLabel(event.target.value)}/>
        <label htmlFor="cosy-upload-transcript">录音原文</label><Input.TextArea id="cosy-upload-transcript" maxLength={500} disabled={locked} rows={3} value={transcript} onChange={event => setTranscript(event.target.value)}/>
        <Button disabled={locked || !snapshot || !file || !label.trim() || !transcript.trim()} onClick={() => void run(async () => {
          if (!file || file.size > 4 * 1024 * 1024 || !/\.wav$/i.test(file.name)) throw new ApiError('invalid_voice_reference', 400);
          const data = await api.request<{item: Reference; references: Reference[]}>('/api/voice-references', 'POST', {audio_base64: await fileBase64(file), label, transcript});
          if (mounted.current && snapshot) {setSnapshot({...snapshot, references: data.references}); setDraft({...draft, reference_id: data.item.id, transcript: data.item.transcript}); clearAudio(); setNotice('录音已加入参考库，已选入草稿；试听并保存后才切换日用声线。');}
        })}>上传到参考库</Button>
      </Space></details>
      <label htmlFor="cosy-reference">参考声线</label>
      <Select id="cosy-reference" aria-label="参考声线" className="wide" value={draft.reference_id ?? '__default__'} disabled={locked || !snapshot}
        options={[{value: '__default__', label: '原日用声线（官方参考音频）'}, ...(snapshot?.references ?? []).map(item => ({value: item.id, label: `${item.label} · ${item.duration_seconds} 秒`}))]}
        onChange={id => {clearAudio(); setDraft({...draft, reference_id: id === '__default__' ? null : id, transcript: id === '__default__' ? '' : snapshot?.references.find(item => item.id === id)?.transcript ?? ''});}}/>
      {draft.reference_id && <><label htmlFor="cosy-reference-transcript">参考录音中的原文</label><Input.TextArea id="cosy-reference-transcript" maxLength={500} rows={3} value={draft.transcript} disabled={locked} onChange={event => {clearAudio(); setDraft({...draft, transcript: event.target.value});}}/><small>不填写表达指令时，模型用这段原文匹配录音，请保持逐字准确。</small></>}
      <label htmlFor="cosy-style">表达指令（可留空）</label>
      <Input id="cosy-style" maxLength={200} value={draft.style} disabled={locked} placeholder="例如：温柔亲切地说话" onChange={event => {clearAudio(); setDraft({...draft, style: event.target.value});}}/>
      <Space wrap>{styles.map(style => <Button key={style} size="small" disabled={locked} onClick={() => {clearAudio(); setDraft({...draft, style});}}>{style.replace('地说话', '')}</Button>)}</Space>
      <small>留空时使用参考原文克隆；填写后使用模型的指令合成模式。相似度与语气控制效果会随录音和指令变化。</small>
      </Space>
    </section>
    <section className="voice-audition" aria-label="试听与保存">
      <h4>试听与保存</h4>
      <p>试听只生成草稿音频。保存后，网页与圆屏共用这份声线；正在生成的语音保持开始时的声音。</p>
      <Space wrap>
        <Button disabled={locked || !snapshot || snapshot.service_state !== 'ready' || Boolean(draft.reference_id && !draft.transcript.trim())} onClick={() => void run(async () => {clearAudio(); const blob = await api.cosyVoicePreview({...draft}); if (mounted.current) {audioRef.current = URL.createObjectURL(blob); setAudio(audioRef.current); setNotice('草稿试听已生成；尚未保存到日用声线。');}})}>试听草稿</Button>
        <Button type="primary" disabled={locked || !snapshot || Boolean(draft.reference_id && !draft.transcript.trim())} onClick={() => void run(async () => {
          const next = await api.request<Snapshot>('/api/voice-profile', 'POST', {profile: draft, expected_profile_digest: snapshot?.profile_digest});
          if (mounted.current) {setSnapshot(next); setDraft(next.profile); clearAudio(); setNotice(next.activation === 'next_synthesis' ? '声音档案已保存，网页和圆屏从下一次合成开始使用；当前语音保持原声线。' : '声音档案已保存；启动新版 CosyVoice 3 服务后生效，当前声线尚未切换。');}
        })}>保存日用声线</Button>
        <Button disabled={locked} onClick={() => {clearAudio(); setDraft({...defaultProfile}); setNotice('已恢复原日用声线草稿，保存后才会生效。');}}>恢复原声线草稿</Button>
        <Button disabled={locked} onClick={() => dirty ? setReloadRequested(true) : void run(load)}>重新读取声音档案</Button>
      </Space>
      {reloadRequested && <Alert type="warning" title="重新读取会放弃当前草稿" description="其他页面已保存的档案会成为新的编辑起点。"
        action={<Space wrap><Button disabled={locked} onClick={() => void run(load)}>放弃草稿并重新读取</Button><Button disabled={locked} onClick={() => setReloadRequested(false)}>保留草稿</Button></Space>}/>}
      {audio && <audio src={audio} controls aria-label="CosyVoice 声音草稿试听"/>}
      {snapshot && <small>固定试听文本：{snapshot.preview_text}</small>}
      <p className="voice-activation">{snapshot?.activation === 'next_synthesis' ? '生效时机：保存后的下一次合成。' : '生效时机：启动支持声音档案的服务后。'}录音相似度与实际语气仍需听感核对。</p>
    </section>
    </div>
  </section>;
}
