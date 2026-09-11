import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, InputNumber, Select, Slider, Space, Tag} from 'antd';
import {ApiError, ChatApi, type DeviceStatus, type NaturalInterruptionDiagnostic, type VoiceLatency} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {errorMessage, resultView, statusView, validTarget} from '../../assets/state.mjs';

type VolumeRead = {volume: number};
type VolumeWrite = {requested_volume: number; previous_volume?: number; acknowledged: boolean; readback_volume?: number; verified?: boolean};
type DeviceSnapshot = {volume?:number; brightness?:number; theme?:'light'|'dark'; battery?:{level:number;charging:boolean}; network?:{signal:'strong'|'medium'|'weak'}; chip?:{temperature:number}};
type ScreenWrite = {requested_value:number|string; previous_value?:number|string; acknowledged:boolean; readback_value?:number|string; verified:boolean};
type StopSpeechResult = {operation_id:string; state:'stop_sent'|'already_idle'; server_interrupted:boolean; device_acknowledgement:'unavailable'|'not_requested'};
type Operation = {action: 'read' | 'set'; data?: VolumeRead | VolumeWrite | ScreenWrite; error?: string; at: string};

const api = new ChatApi();
const clock = () => new Date().toLocaleTimeString('zh-CN', {hour12: false});
const codeOf = (error: unknown) => error instanceof ApiError ? error.code : 'request_failed';
const elapsed = (value:number|null|undefined) => value === null || value === undefined ? '尚未到达' : `${(value / 1000).toFixed(2)} 秒`;
const delta = (end:number|null, start:number|null) => end === null || start === null ? '尚未测得' : elapsed(Math.max(0, end - start));

function VoiceLatencyCard({value}:{value:VoiceLatency}) {
  const timing=value.timings_ms;
  const stateLabels:Record<VoiceLatency['state'],string>={
    preparing_memory:'准备记忆', waiting_for_model:'等待模型', waiting_for_sentence:'组织首句',
    tts_running:'生成语音', audio_ready:'音频已就绪', first_audio_sent:'首包已发送',
  };
  return <Card className="device-latency-card" title="最近一次圆屏首句时序" extra={<Tag color={value.state==='first_audio_sent'?'green':'processing'}>{stateLabels[value.state]}</Tag>}>
    <Descriptions column={{xs:1,sm:2,lg:3}} size="small" items={[
      {key:'memory',label:'入口 → 记忆完成',children:elapsed(timing.memory_ready_ms)},
      {key:'model',label:'模型首个有效输出',children:delta(timing.llm_first_output_ms,timing.llm_requested_ms)},
      {key:'sentence',label:'输出 → 攒成首句',children:delta(timing.tts_started_ms,timing.llm_first_output_ms)},
      {key:'tts',label:'TTS 生成与编码',children:delta(timing.audio_ready_ms,timing.tts_started_ms)},
      {key:'delivery',label:'音频就绪 → 首包发送',children:delta(timing.first_audio_sent_ms,timing.audio_ready_ms)},
      {key:'total',label:'入口 → 首包发送',children:<strong>{elapsed(timing.first_audio_sent_ms)}</strong>},
    ]}/>
    <p className="subtle">计时起点是服务端收到已识别文本并进入回答流程；不含录音与 ASR，也不代表扬声器真正开始出声。当前后端：{value.tts_backend==='edge'?'EdgeTTS':value.tts_backend==='voxcpm2'?'VoxCPM2':value.tts_backend==='sanotts'?'sanoTTS':'其他'}。</p>
  </Card>;
}

function NaturalInterruptionCard({value}:{value:NaturalInterruptionDiagnostic}) {
  const reason:Record<NaturalInterruptionDiagnostic['reason'],{title:string;description:string}>={
    device_offline:{title:'等待圆屏连接',description:'当前没有可核对的活动圆屏连接。唤醒设备后，本页会自动刷新诊断。'},
    device_aec_not_advertised:{title:'固件未声明服务端 AEC',description:'当前圆屏握手没有上报 aec，不能假定它会在播放时持续发送可消除回声的麦克风音频。'},
    timestamp_transport_unavailable:{title:'直连传输缺少时间戳配对',description:'当前小智直连 WebSocket 路径不解析 AEC 时间戳；服务端无法可靠匹配扬声器参考帧与麦克风帧。'},
    server_aec_inactive:{title:'服务端 AEC 尚未激活',description:'设备声明与服务端连接状态不一致，不能开始自然打断测试。'},
    realtime_listening_inactive:{title:'圆屏未进入实时拾音',description:'自然插话需要回答播放期间保持实时聆听；当前模式尚不满足。'},
    ready_for_controlled_trial:{title:'具备受控试验前提',description:'基础信号均已成立，但仍需用扬声器回声、近讲和远讲场景验证误触发与漏触发。'},
  };
  const result=reason[value.reason];
  const yes=(flag:boolean)=>flag?'满足':'未满足';
  const mode={auto:'自动停录',manual:'手动停录',realtime:'实时拾音',unknown:'未知'}[value.listen_mode];
  return <Card className="device-control-card" title="自然说话打断" extra={<Tag color={value.state==='trial_ready'?'green':value.state==='blocked'?'gold':'default'}>{value.state==='trial_ready'?'可试验':value.state==='blocked'?'有阻塞':'不可用'}</Tag>}>
    <Alert showIcon type={value.state==='trial_ready'?'success':'warning'} title={result.title} description={result.description}/>
    <Descriptions className="device-help" column={1} size="small" items={[
      {key:'device',label:'设备 AEC 声明',children:yes(value.device_aec_advertised)},
      {key:'timestamp',label:'时间戳音频传输',children:yes(value.timestamped_audio_supported)},
      {key:'server',label:'服务端 AEC',children:yes(value.server_aec_active)},
      {key:'listen',label:'当前拾音模式',children:mode},
    ]}/>
    <p className="subtle">这里只显示能力证据，不会自动开启 AEC，也不会把控制台按钮停止算作自然语音打断。</p>
  </Card>;
}

/**
 * 设备页是 TanStack Query 的首个真实落点：状态是可缓存、可轮询的服务器状态；
 * 读取/设置音量仍是用户明确触发的 mutation，不会因为失败而自动重放。
 */
export function DeviceApp() {
  const client = useQueryClient();
  const [target, setTarget] = useState<number | null>(30);
  const [brightness, setBrightness] = useState<number | null>(50);
  const [theme, setTheme] = useState<'light'|'dark'>('light');
  const [reading, setReading] = useState<{value: number; at: number}>();
  const [snapshot, setSnapshot] = useState<DeviceSnapshot>();
  const [snapshotAt, setSnapshotAt] = useState<number>();
  const [operation, setOperation] = useState<Operation>();
  const [stopResult, setStopResult] = useState<StopSpeechResult>();
  const [stopError, setStopError] = useState<string>();
  const session = useQuery({queryKey: ['console-session'], queryFn: async () => {await api.bootstrap(); return true;}, staleTime: Infinity});
  const status = useQuery({
    queryKey: ['device-status'],
    queryFn: () => api.request<DeviceStatus>('/api/device'),
    enabled: session.isSuccess,
    refetchInterval: 5000,
    refetchOnWindowFocus: true,
  });
  // 轮询失败后不能继续展示旧的“可控制”状态，否则用户可能对离线设备发出写操作。
  const view = statusView(status.error ? {error: codeOf(status.error)} : status.data);

  useEffect(() => {
    if (!view.read || (reading && Date.now() - reading.at > 30000)) setReading(undefined);
  }, [view.read, status.dataUpdatedAt]);

  async function refreshAfterOperation() {
    await client.invalidateQueries({queryKey: ['device-status']});
  }
  const readVolume = useMutation({
    mutationFn: () => api.request<VolumeRead>('/api/device/volume'),
    onSuccess(data) {setReading({value: data.volume, at: Date.now()}); setOperation({action:'read', data, at:clock()});},
    onError(error) {setReading(undefined); setOperation({action:'read', error:codeOf(error), at:clock()});},
    onSettled: refreshAfterOperation,
  });
  const setVolume = useMutation({
    mutationFn: (volume: number) => api.request<VolumeWrite>('/api/device/volume', 'POST', {volume}),
    onSuccess(data) {
      if (Number.isInteger(data.readback_volume)) setReading({value:data.readback_volume!, at:Date.now()});
      else setReading(undefined);
      setOperation({action:'set', data, at:clock()});
    },
    onError(error) {setReading(undefined); setOperation({action:'set', error:codeOf(error), at:clock()});},
    onSettled: refreshAfterOperation,
  });
  const readSnapshot = useMutation({
    mutationFn: () => api.request<DeviceSnapshot>('/api/device/snapshot'),
    onSuccess(data) {
      const at = Date.now();
      setSnapshot(data); setSnapshotAt(at);
      if (Number.isInteger(data.volume)) setReading({value:data.volume!, at});
    },
    onError(error) {setOperation({action:'read', error:codeOf(error), at:clock()});},
    onSettled: refreshAfterOperation,
  });
  const setScreen = useMutation({
    mutationFn: (setting: {brightness:number}|{theme:'light'|'dark'}) => api.request<ScreenWrite>('/api/device/screen', 'POST', setting),
    onSuccess(data) {setOperation({action:'set', data, at:clock()}); void readSnapshot.mutateAsync();},
    onError(error) {setOperation({action:'set', error:codeOf(error), at:clock()});},
    onSettled: refreshAfterOperation,
  });
  const stopSpeech = useMutation({
    mutationFn: () => api.request<StopSpeechResult>('/api/device/speech/stop', 'POST'),
    onSuccess(data) {setStopResult(data); setStopError(undefined);},
    onError(error) {setStopResult(undefined); setStopError(codeOf(error));},
    onSettled: refreshAfterOperation,
  });
  const busy = readVolume.isPending || setVolume.isPending || readSnapshot.isPending || setScreen.isPending || stopSpeech.isPending;
  const operationView = operation ? resultView(operation.error ? {error:operation.error} : operation.data, operation.action) : null;
  const operationDetails = (operationView?.details ?? []) as Array<[string, unknown]>;
  const sidebar = <><ConsoleNav active="device" legacyPath="/"/><Card size="small" className="device-boundary-card" title="控制边界"><p>开放音量、亮度和明暗主题；电池、网络与温度只读。</p><p>重启、配网和刷写仍不开放。</p></Card></>;

  return <AppShell subtitle="智能圆屏终端管理" className="device-shell" sidebar={sidebar}>
    <PageHeader eyebrow="日常使用" title="设备与状态" description="查看 SmartRing-Plus 圆屏终端，并控制固件已上报且可回读核对的基础能力。"
      meta="连接状态每 5 秒检查；设备详细状态只在你点击读取时更新。"
      action={<Button loading={readSnapshot.isPending} disabled={!session.isSuccess || busy || !status.data?.read_status_supported} onClick={() => readSnapshot.mutate()}>读取设备快照</Button>}/>
    {session.isError && <Alert type="error" showIcon title="无法建立控制台会话" description="请确认本机网页服务仍在运行，再刷新页面。没有自动重发设备指令。"/>}
    <Card className={`device-summary-card tone-${view.tone}`}>
      <div className="device-status-hero"><span className="device-status-dot" aria-hidden="true"/><div><small>SMART RING TERMINAL</small><h2>SmartRing-Plus B V2</h2><p>{view.help}</p></div><Tag color={view.tone === 'good' ? 'green' : view.tone === 'warning' ? 'gold' : 'red'}>{view.badge}</Tag></div>
      <div className="device-status-grid">
        <div><small>小智控制服务</small><strong>{view.bridge}</strong></div>
        <div><small>圆屏连接</small><strong>{view.device}</strong></div>
        <div><small>设备工具</small><strong>{view.tools}</strong></div>
        <div><small>说话打断基础</small><strong>{status.data?.aec_advertised?'固件已上报 AEC':'未上报 AEC'}</strong></div>
      </div><div className="device-refresh-meta"><span>{status.data?.connection_count ?? 0} 个活动连接</span><span>{status.dataUpdatedAt ? `刷新于 ${new Date(status.dataUpdatedAt).toLocaleTimeString('zh-CN', {hour12:false})}` : '尚未刷新'}</span><span>每 5 秒检查连接，不轮询音量</span></div>
    </Card>
    {status.data?.voice_latency && <VoiceLatencyCard value={status.data.voice_latency}/>}
    {status.data?.natural_interruption && <NaturalInterruptionCard value={status.data.natural_interruption}/>}
    {snapshot && <Card className="device-snapshot-card" title="最近设备快照" extra={<Tag color={status.data?.ready && !status.error ? 'blue' : 'gold'}>{status.data?.ready && !status.error ? '单次读取' : '历史读数'}</Tag>}><Descriptions column={{xs:1,sm:3}} items={[
      {key:'battery',label:'电池',children:snapshot.battery ? `${snapshot.battery.level}% · ${snapshot.battery.charging?'充电中':'未充电'}` : '固件未报告'},
      {key:'network',label:'Wi‑Fi 信号',children:snapshot.network?.signal === 'strong'?'强':snapshot.network?.signal === 'medium'?'中':snapshot.network?.signal === 'weak'?'弱':'固件未报告'},
      {key:'temperature',label:'芯片温度',children:snapshot.chip ? `${snapshot.chip.temperature} ℃` : '固件未报告'},
      {key:'brightness',label:'屏幕亮度',children:snapshot.brightness ?? '固件未报告'},
      {key:'theme',label:'屏幕主题',children:snapshot.theme === 'dark'?'深色':snapshot.theme === 'light'?'浅色':'固件未报告'},
    ]}/><p className="subtle">读取于 {snapshotAt ? new Date(snapshotAt).toLocaleTimeString('zh-CN', {hour12:false}) : '未知时间'}。这是一次主动读取，不是持续监测；为保护隐私不显示 Wi‑Fi 名称。{(!status.data?.ready || status.error) ? ' 当前连接不可用，上述内容只代表上一次成功快照。' : ''}</p></Card>}
    <div className="device-grid">
      <Card className="device-control-card" title="扬声器音量" extra={<Tag color={view.set ? 'green' : 'default'}>{view.set ? '可控' : '不可控'}</Tag>}>
        <div className="device-card-action"><Button disabled={!view.read || busy} loading={readVolume.isPending} onClick={() => readVolume.mutate()}>读取当前值</Button></div>
        <div className="volume-value"><strong>{reading?.value ?? '—'}</strong><span>/ {status.data?.allowed_volume?.maximum ?? 60}</span></div>
        <p className="subtle">{reading ? `最近读取于 ${new Date(reading.at).toLocaleTimeString('zh-CN', {hour12:false})}；不是持续监测。` : '还没有可用的设备音量读数。'}</p>
        <label htmlFor="device-volume">目标音量</label>
        <Space.Compact block><Slider id="device-volume" className="volume-slider" min={5} max={60} value={target ?? 30} disabled={!view.set || busy} onChange={setTarget}/><InputNumber min={5} max={60} value={target} disabled={!view.set || busy} onChange={setTarget}/></Space.Compact>
        <p className="subtle">选择数值不会发送；点击后才设置。范围 5–60，不改变语速或音色。</p>
        <Button type="primary" loading={setVolume.isPending} disabled={!view.set || busy || !validTarget(target)} onClick={() => {if (validTarget(target)) setVolume.mutate(target!);}}>应用音量</Button>
      </Card>
      <Card className="device-control-card" title="屏幕显示" extra={<Tag color={status.data?.set_brightness_supported || status.data?.set_theme_supported ? 'green' : 'default'}>{status.data?.set_brightness_supported || status.data?.set_theme_supported ? '部分可控' : '不可控'}</Tag>}>
        <label htmlFor="device-brightness">目标亮度</label>
        <Space.Compact block><Slider id="device-brightness" className="volume-slider" min={5} max={100} value={brightness ?? 50} disabled={!status.data?.set_brightness_supported || busy} onChange={setBrightness}/><InputNumber min={5} max={100} value={brightness} disabled={!status.data?.set_brightness_supported || busy} onChange={setBrightness}/></Space.Compact>
        <Button disabled={!status.data?.set_brightness_supported || busy || !Number.isInteger(brightness)} onClick={() => setScreen.mutate({brightness:brightness!})}>应用亮度</Button>
        <label htmlFor="device-theme">明暗主题</label>
        <Select id="device-theme" className="wide" value={theme} disabled={!status.data?.set_theme_supported || busy} options={[{value:'light',label:'浅色'},{value:'dark',label:'深色'}]} onChange={setTheme}/>
        <Button disabled={!status.data?.set_theme_supported || busy} onClick={() => setScreen.mutate({theme})}>应用主题</Button>
        <p className="subtle">按钮不可用表示当前圆屏没有实时上报对应工具；页面不会根据源码猜测。</p>
      </Card>
      <Card className="device-control-card" title="当前回答" extra={<Tag color={status.data?.stop_speech_supported ? 'green' : 'default'}>{status.data?.stop_speech_supported ? '可中止' : '不可用'}</Tag>}>
        <p>在圆屏回答过长、语音生成过慢或你想换个话题时，立即停止当前轮。</p>
        <Button danger type="primary" loading={stopSpeech.isPending} disabled={!status.data?.ready || !status.data?.stop_speech_supported || busy} onClick={() => stopSpeech.mutate()}>停止当前回答</Button>
        {stopResult && <Alert className="device-help" showIcon type={stopResult.state==='stop_sent'?'success':'info'} title={stopResult.state==='stop_sent'?'已中止服务端回答':'当前已经处于空闲'} description={stopResult.state==='stop_sent'?'已清空模型与 TTS 队列，并向圆屏发送停止指令。设备协议没有播放停止回执，因此不写成“硬件已确认”。':'没有正在生成或播放的回答，本次未发送停止指令。'}/>}
        {stopError && <Alert className="device-help" showIcon type="error" title="未能中止当前回答" description={errorMessage(stopError)}/>}
        <p className="subtle">这不会删除对话或记忆，也不会断开圆屏。不等待亮度、音量等 MCP 工具回执。</p>
      </Card>
      <Card className="device-operation-card" title="最近一次操作">
        {operationView ? <><h3>{operationView.title}</h3><p>{operationView.description}</p><Descriptions column={1} size="small" items={[...operationDetails.map(([label, value], index) => ({key:String(index), label, children:String(value)})), {key:'time',label:'操作时间',children:operation!.at}]}/></> : <><h3>尚未发送指令</h3><p>先读取当前音量，或选择目标音量后应用。</p></>}
        <p className="subtle">若请求超时，音量可能已经改变。先读取核对，不要连续重试。</p>
      </Card>
    </div>
    <Alert className="device-help" type="info" showIcon title="待机时可能暂不可控" description="圆屏进入聆听状态后才可能建立活动连接。显示“请唤醒圆屏”时，先轻触设备，再刷新状态；不需要重新配网。"/>
    {operation?.error && <p role="status">{errorMessage(operation.error)}</p>}
  </AppShell>;
}
