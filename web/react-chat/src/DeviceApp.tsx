import {useEffect, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Descriptions, InputNumber, Slider, Space, Tag} from 'antd';
import {ApiError, ChatApi} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {errorMessage, resultView, statusView, validTarget} from '../../assets/state.mjs';

type DeviceStatus = {
  connection_count: number;
  ready: boolean;
  read_volume_supported: boolean;
  set_volume_supported: boolean;
  allowed_volume?: {minimum: number; maximum: number};
};
type VolumeRead = {volume: number};
type VolumeWrite = {requested_volume: number; previous_volume?: number; acknowledged: boolean; readback_volume?: number; verified?: boolean};
type Operation = {action: 'read' | 'set'; data?: VolumeRead | VolumeWrite; error?: string; at: string};

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
  const [reading, setReading] = useState<{value: number; at: number}>();
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
  const busy = readVolume.isPending || setVolume.isPending;
  const operationView = operation ? resultView(operation.error ? {error:operation.error} : operation.data, operation.action) : null;
  const operationDetails = (operationView?.details ?? []) as Array<[string, unknown]>;
  const sidebar = <><ConsoleNav active="device" legacyPath="/"/><Card size="small" title="控制边界"><p>当前只开放扬声器音量。电量、亮度、屏幕 UI 和重启尚无已验证控制接口。</p></Card></>;

  return <AppShell subtitle="智能圆屏终端管理" className="device-shell" sidebar={sidebar}>
    <PageHeader eyebrow="日常使用" title="设备与状态" description="查看 SmartRing-Plus 圆屏终端是否在线，并读取或调整已验证的扬声器音量。"
      meta="连接状态每 5 秒自动检查；设备音量只在你点击读取时更新。"
      action={<Button loading={status.isFetching} disabled={!session.isSuccess || busy} onClick={() => void status.refetch()}>刷新状态</Button>}/>
    {session.isError && <Alert type="error" showIcon title="无法建立控制台会话" description="请确认本机网页服务仍在运行，再刷新页面。没有自动重发设备指令。"/>}
    <Card className="device-summary-card" title="SmartRing-Plus B V2" extra={<Tag color={view.tone === 'good' ? 'green' : view.tone === 'warning' ? 'gold' : 'red'}>{view.badge}</Tag>}>
      <Descriptions column={{xs:1, sm:3}} items={[
        {key:'bridge',label:'小智控制服务',children:view.bridge},
        {key:'device',label:'圆屏连接',children:view.device},
        {key:'tools',label:'音量工具',children:view.tools},
      ]}/><p>{view.help}</p><small>{status.dataUpdatedAt ? `刷新于 ${new Date(status.dataUpdatedAt).toLocaleTimeString('zh-CN', {hour12:false})}` : '尚未刷新'} · 每 5 秒检查连接，不轮询设备音量</small>
    </Card>
    <div className="device-grid">
      <Card title="扬声器音量" extra={<Button disabled={!view.read || busy} loading={readVolume.isPending} onClick={() => readVolume.mutate()}>读取当前值</Button>}>
        <div className="volume-value"><strong>{reading?.value ?? '—'}</strong><span>/ 100</span></div>
        <p className="subtle">{reading ? `最近读取于 ${new Date(reading.at).toLocaleTimeString('zh-CN', {hour12:false})}；不是持续监测。` : '还没有可用的设备音量读数。'}</p>
        <label htmlFor="device-volume">目标音量</label>
        <Space.Compact block><Slider id="device-volume" className="volume-slider" min={5} max={60} value={target ?? 30} disabled={!view.set || busy} onChange={setTarget}/><InputNumber min={5} max={60} value={target} disabled={!view.set || busy} onChange={setTarget}/></Space.Compact>
        <p className="subtle">选择数值不会发送；点击后才设置。范围 5–60，不改变语速或音色。</p>
        <Button type="primary" loading={setVolume.isPending} disabled={!view.set || busy || !validTarget(target)} onClick={() => {if (validTarget(target)) setVolume.mutate(target!);}}>应用音量</Button>
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
