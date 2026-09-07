import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, InputNumber, Select, Slider, Space, Tag} from 'antd';
import {ApiError, ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {errorMessage, resultView, statusView, validTarget} from '../../assets/state.mjs';

type DeviceStatus = {
  connection_count: number;
  ready: boolean;
  read_volume_supported: boolean;
  set_volume_supported: boolean;
  read_status_supported: boolean;
  set_brightness_supported: boolean;
  set_theme_supported: boolean;
  aec_advertised?: boolean;
  allowed_volume?: {minimum: number; maximum: number};
};
type VolumeRead = {volume: number};
type VolumeWrite = {requested_volume: number; previous_volume?: number; acknowledged: boolean; readback_volume?: number; verified?: boolean};
type DeviceSnapshot = {volume?:number; brightness?:number; theme?:'light'|'dark'; battery?:{level:number;charging:boolean}; network?:{signal:'strong'|'medium'|'weak'}; chip?:{temperature:number}};
type ScreenWrite = {requested_value:number|string; previous_value?:number|string; acknowledged:boolean; readback_value?:number|string; verified:boolean};
type Operation = {action: 'read' | 'set'; data?: VolumeRead | VolumeWrite | ScreenWrite; error?: string; at: string};

const api = new ChatApi();
const clock = () => new Date().toLocaleTimeString('zh-CN', {hour12: false});
const codeOf = (error: unknown) => error instanceof ApiError ? error.code : 'request_failed';

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
  const [operation, setOperation] = useState<Operation>();
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
    onSuccess(data) {setSnapshot(data); if (Number.isInteger(data.volume)) setReading({value:data.volume!, at:Date.now()});},
    onError(error) {setOperation({action:'read', error:codeOf(error), at:clock()});},
    onSettled: refreshAfterOperation,
  });
  const setScreen = useMutation({
    mutationFn: (setting: {brightness:number}|{theme:'light'|'dark'}) => api.request<ScreenWrite>('/api/device/screen', 'POST', setting),
    onSuccess(data) {setOperation({action:'set', data, at:clock()}); void readSnapshot.mutateAsync();},
    onError(error) {setOperation({action:'set', error:codeOf(error), at:clock()});},
    onSettled: refreshAfterOperation,
  });
  const busy = readVolume.isPending || setVolume.isPending || readSnapshot.isPending || setScreen.isPending;
  const operationView = operation ? resultView(operation.error ? {error:operation.error} : operation.data, operation.action) : null;
  const operationDetails = (operationView?.details ?? []) as Array<[string, unknown]>;
  const sidebar = <><ConsoleNav active="device" legacyPath="/"/><Card size="small" title="控制边界"><p>开放音量、亮度和明暗主题；电池、网络与温度只读。重启、配网和刷写仍不开放。</p></Card></>;

  return <AppShell subtitle="智能圆屏终端管理" className="device-shell" sidebar={sidebar}>
    <PageHeader eyebrow="日常使用" title="设备与状态" description="查看 SmartRing-Plus 圆屏终端，并控制固件已上报且可回读核对的基础能力。"
      meta="连接状态每 5 秒检查；设备详细状态只在你点击读取时更新。"
      action={<Button loading={readSnapshot.isPending} disabled={!session.isSuccess || busy || !status.data?.read_status_supported} onClick={() => readSnapshot.mutate()}>读取设备快照</Button>}/>
    {session.isError && <Alert type="error" showIcon title="无法建立控制台会话" description="请确认本机网页服务仍在运行，再刷新页面。没有自动重发设备指令。"/>}
    <Card className="device-summary-card" title="SmartRing-Plus B V2" extra={<Tag color={view.tone === 'good' ? 'green' : view.tone === 'warning' ? 'gold' : 'red'}>{view.badge}</Tag>}>
      <Descriptions column={{xs:1, sm:3}} items={[
        {key:'bridge',label:'小智控制服务',children:view.bridge},
        {key:'device',label:'圆屏连接',children:view.device},
        {key:'tools',label:'设备工具',children:view.tools},
        {key:'aec',label:'说话打断基础',children:status.data?.aec_advertised?'固件已上报 AEC':'未上报 AEC'},
      ]}/><p>{view.help}</p><small>{status.dataUpdatedAt ? `刷新于 ${new Date(status.dataUpdatedAt).toLocaleTimeString('zh-CN', {hour12:false})}` : '尚未刷新'} · 每 5 秒检查连接，不轮询设备音量</small>
    </Card>
    {snapshot && <Card title="最近设备快照"><Descriptions column={{xs:1,sm:3}} items={[
      {key:'battery',label:'电池',children:snapshot.battery ? `${snapshot.battery.level}% · ${snapshot.battery.charging?'充电中':'未充电'}` : '固件未报告'},
      {key:'network',label:'Wi‑Fi 信号',children:snapshot.network?.signal === 'strong'?'强':snapshot.network?.signal === 'medium'?'中':snapshot.network?.signal === 'weak'?'弱':'固件未报告'},
      {key:'temperature',label:'芯片温度',children:snapshot.chip ? `${snapshot.chip.temperature} ℃` : '固件未报告'},
      {key:'brightness',label:'屏幕亮度',children:snapshot.brightness ?? '固件未报告'},
      {key:'theme',label:'屏幕主题',children:snapshot.theme === 'dark'?'深色':snapshot.theme === 'light'?'浅色':'固件未报告'},
    ]}/><p className="subtle">这是一次主动读取，不是持续监测；为保护隐私不显示 Wi‑Fi 名称。</p></Card>}
    <div className="device-grid">
      <Card title="扬声器音量" extra={<Button disabled={!view.read || busy} loading={readVolume.isPending} onClick={() => readVolume.mutate()}>读取当前值</Button>}>
        <div className="volume-value"><strong>{reading?.value ?? '—'}</strong><span>/ 100</span></div>
        <p className="subtle">{reading ? `最近读取于 ${new Date(reading.at).toLocaleTimeString('zh-CN', {hour12:false})}；不是持续监测。` : '还没有可用的设备音量读数。'}</p>
        <label htmlFor="device-volume">目标音量</label>
        <Space.Compact block><Slider id="device-volume" className="volume-slider" min={5} max={60} value={target ?? 30} disabled={!view.set || busy} onChange={setTarget}/><InputNumber min={5} max={60} value={target} disabled={!view.set || busy} onChange={setTarget}/></Space.Compact>
        <p className="subtle">选择数值不会发送；点击后才设置。范围 5–60，不改变语速或音色。</p>
        <Button type="primary" loading={setVolume.isPending} disabled={!view.set || busy || !validTarget(target)} onClick={() => {if (validTarget(target)) setVolume.mutate(target!);}}>应用音量</Button>
      </Card>
      <Card title="屏幕显示">
        <label htmlFor="device-brightness">目标亮度</label>
        <Space.Compact block><Slider id="device-brightness" className="volume-slider" min={5} max={100} value={brightness ?? 50} disabled={!status.data?.set_brightness_supported || busy} onChange={setBrightness}/><InputNumber min={5} max={100} value={brightness} disabled={!status.data?.set_brightness_supported || busy} onChange={setBrightness}/></Space.Compact>
        <Button disabled={!status.data?.set_brightness_supported || busy || !Number.isInteger(brightness)} onClick={() => setScreen.mutate({brightness:brightness!})}>应用亮度</Button>
        <label htmlFor="device-theme">明暗主题</label>
        <Select id="device-theme" className="wide" value={theme} disabled={!status.data?.set_theme_supported || busy} options={[{value:'light',label:'浅色'},{value:'dark',label:'深色'}]} onChange={setTheme}/>
        <Button disabled={!status.data?.set_theme_supported || busy} onClick={() => setScreen.mutate({theme})}>应用主题</Button>
        <p className="subtle">按钮不可用表示当前圆屏没有实时上报对应工具；页面不会根据源码猜测。</p>
      </Card>
      <Card title="最近一次操作">
        {operationView ? <><h3>{operationView.title}</h3><p>{operationView.description}</p><Descriptions column={1} size="small" items={[...operationDetails.map(([label, value], index) => ({key:String(index), label, children:String(value)})), {key:'time',label:'操作时间',children:operation!.at}]}/></> : <><h3>尚未发送指令</h3><p>先读取当前音量，或选择目标音量后应用。</p></>}
        <p className="subtle">若请求超时，音量可能已经改变。先读取核对，不要连续重试。</p>
      </Card>
    </div>
    <Alert className="device-help" type="info" showIcon title="待机时可能暂不可控" description="圆屏进入聆听状态后才可能建立活动连接。显示“请唤醒圆屏”时，先轻触设备，再刷新状态；不需要重新配网。"/>
    {operation?.error && <p role="status">{errorMessage(operation.error)}</p>}
  </AppShell>;
}
