import {useEffect, useMemo, useState, type CSSProperties} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, Descriptions, Segmented, Select, Space, Tag} from 'antd';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {ChatApi, type RoundSkin, type RoundSkins} from './api';

export type InteractionState = 'booting' | 'idle' | 'wake_acknowledged' | 'listening' | 'thinking' | 'speaking' | 'interrupted' | 'no_speech' | 'error';
export type EmotionState = 'neutral' | 'warm' | 'happy' | 'concerned';
export type SystemState = 'normal' | 'charging' | 'low_battery' | 'network_offline' | 'model_unavailable' | 'server_unavailable' | 'provisioning' | 'updating';

type Presentation = {
  title: string;
  caption: string;
  tone: 'normal' | 'active' | 'warning' | 'error';
  focus: 'face' | 'progress' | 'notice';
};

const interactionCopy: Record<InteractionState, Presentation> = {
  booting: {title: '正在启动', caption: '稍等一下，很快就好', tone: 'normal', focus: 'progress'},
  idle: {title: '待机', caption: '轻触或叫我一声', tone: 'normal', focus: 'face'},
  wake_acknowledged: {title: '我在', caption: '正在听你说', tone: 'active', focus: 'face'},
  listening: {title: '聆听中', caption: '请继续说', tone: 'active', focus: 'face'},
  thinking: {title: '想一想', caption: '正在组织回答', tone: 'active', focus: 'progress'},
  speaking: {title: '回应中', caption: '点击或说话可以打断', tone: 'active', focus: 'face'},
  interrupted: {title: '听到了', caption: '已停止回答，请继续说', tone: 'active', focus: 'face'},
  no_speech: {title: '没听清', caption: '可以再说一次吗？', tone: 'warning', focus: 'notice'},
  error: {title: '暂时出了问题', caption: '请稍后再试', tone: 'error', focus: 'notice'},
};

const systemCopy: Partial<Record<SystemState, Presentation>> = {
  provisioning: {title: '配网模式', caption: '请按设备提示连接网络', tone: 'active', focus: 'notice'},
  updating: {title: '正在更新', caption: '请保持供电，不要关闭设备', tone: 'active', focus: 'progress'},
  network_offline: {title: '网络未连接', caption: '请检查 Wi-Fi 或重新配网', tone: 'error', focus: 'notice'},
  model_unavailable: {title: '模型暂时不可用', caption: '设备正常，回答服务连接失败', tone: 'error', focus: 'notice'},
  server_unavailable: {title: '服务未连接', caption: '请检查电脑端语音服务', tone: 'error', focus: 'notice'},
};

/** 系统阻塞状态优先覆盖对话动画；充电和低电量只作为非阻塞边缘提示。 */
export function resolveRoundDisplay(interaction: InteractionState, system: SystemState): Presentation {
  return systemCopy[system] ?? interactionCopy[interaction];
}

const interactionOptions = [
  ['booting', '启动'], ['idle', '待机'], ['wake_acknowledged', '已唤醒'], ['listening', '聆听'],
  ['thinking', '思考'], ['speaking', '说话'], ['interrupted', '被打断'], ['no_speech', '没听清'], ['error', '错误'],
].map(([value, label]) => ({value, label}));

const systemOptions = [
  ['normal', '正常'], ['charging', '充电中'], ['low_battery', '低电量'], ['network_offline', '网络离线'],
  ['model_unavailable', '模型不可用'], ['server_unavailable', '电脑服务离线'], ['provisioning', '配网'], ['updating', '更新中'],
].map(([value, label]) => ({value, label}));

const emotionOptions = [
  {value: 'neutral', label: '平静'}, {value: 'warm', label: '温柔'},
  {value: 'happy', label: '开心'}, {value: 'concerned', label: '关切'},
];

const api = new ChatApi();

function skinStyle(skin?: RoundSkin): CSSProperties {
  if (!skin) return {};
  return {
    '--round-background': skin.palette.background,
    '--round-background-edge': skin.palette.background_edge,
    '--round-foreground': skin.palette.foreground,
    '--round-muted': skin.palette.muted,
    '--round-accent': skin.palette.accent,
    '--round-warning': skin.palette.warning,
    '--round-error': skin.palette.error,
    '--round-charging': skin.palette.charging,
    '--round-eye-width': `${skin.face.eye_width}px`,
    '--round-eye-height': `${skin.face.eye_height}px`,
    '--round-mouth-width': `${skin.face.mouth_width}px`,
    '--round-blink-seconds': `${skin.motion.blink_seconds}s`,
    '--round-speaking-seconds': `${skin.motion.speaking_seconds}s`,
  } as CSSProperties;
}

export function RoundDisplayApp() {
  const [interaction, setInteraction] = useState<InteractionState>('idle');
  const [emotion, setEmotion] = useState<EmotionState>('warm');
  const [system, setSystem] = useState<SystemState>('normal');
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [selectedSkin, setSelectedSkin] = useState('rose-night-v1');
  const session = useQuery({queryKey:['round-skin-session'], queryFn:async () => {await api.bootstrap(); return true;}, staleTime:Infinity});
  const skins = useQuery({queryKey:['round-skins'], queryFn:() => api.request<RoundSkins>('/api/round-skins'), enabled:session.isSuccess});
  useEffect(() => {if (skins.data?.selected_skin) setSelectedSkin(skins.data.selected_skin);}, [skins.data?.selected_skin]);
  const saveSkin = useMutation({
    mutationFn:(skin_id:string) => api.request<RoundSkins>('/api/round-skins/selection', 'PUT', {skin_id}),
    onSuccess:value => skins.refetch().then(() => setSelectedSkin(value.selected_skin)),
  });
  const view = useMemo(() => resolveRoundDisplay(interaction, system), [interaction, system]);
  const skin = skins.data?.skins.find(item => item.id === selectedSkin);
  const blocked = Boolean(systemCopy[system]);
  const powerLabel = system === 'charging' ? '充电中' : system === 'low_battery' ? '电量低' : '';
  const sidebar = <><ConsoleNav active="display" legacyPath="/"/><Card size="small" title="预览边界">
    <p>这里只模拟板级配置记录的 360×360 圆屏信息层级，不连接设备、不发送指令，也不代表 B V2 固件已经实现。</p>
  </Card></>;

  return <AppShell subtitle="智能圆屏交互实验台" className="display-preview-shell" sidebar={sidebar}>
    <PageHeader eyebrow="体验设计" title="圆屏状态预览" description="先验证待机、聆听、思考、回应和异常是否一眼可辨，再把稳定协议接入真实固件。" meta="画布：360 × 360 px · 中央安全区：约 255 × 255 px"/>
    <Alert type="info" showIcon title="这是设计模拟器，不是真实设备控制器" description="交互状态决定主体动画，情绪只改变表达风格；网络、模型、服务、配网和更新会按优先级覆盖普通对话状态。"/>
    <div className="display-preview-layout">
      <section className="display-stage" aria-label="圆屏模拟画布">
        <div style={skinStyle(skin)} className={`round-display tone-${view.tone} state-${interaction} emotion-${emotion} focus-${view.focus}`}>
          {showSafeArea && <div className="round-safe-area" aria-label="中央安全区"/>}
          <div className="round-topline">{view.title}</div>
          {powerLabel && <div className={`round-power ${system}`}>{powerLabel}</div>}
          <div className="round-focus" aria-live="polite">
            {view.focus === 'progress' && <div className="round-orbit"><i/><i/><i/></div>}
            {view.focus !== 'progress' && <div className="round-face" aria-hidden="true"><i className="eye left"/><i className="eye right"/><i className="mouth"/></div>}
            <strong>{view.title}</strong>
          </div>
          <div className="round-caption">{view.caption}</div>
          {interaction === 'listening' && !blocked && <div className="listening-rings" aria-hidden="true"><i/><i/><i/></div>}
        </div>
      </section>
      <section className="display-controls" aria-label="预览控制">
        <Card title="1. 交互阶段"><p className="subtle">描述系统正在做什么，是圆屏的主状态。</p>
          <Segmented block options={interactionOptions} value={interaction} onChange={value => setInteraction(value as InteractionState)}/>
        </Card>
        <Card title="2. 情绪表达"><p className="subtle">只改变眼神、颜色和动作幅度，不改变交互逻辑。</p>
          <Segmented block options={emotionOptions} value={emotion} onChange={value => setEmotion(value as EmotionState)}/>
        </Card>
        <Card title="3. 系统覆盖"><p className="subtle">阻塞性故障会盖过“聆听/思考/说话”；充电和低电量只显示边缘提示。</p>
          <Select className="wide" aria-label="系统状态" value={system} options={systemOptions} onChange={setSystem}/>
          <Checkbox checked={showSafeArea} onChange={event => setShowSafeArea(event.target.checked)}>显示约 255×255 中央安全区</Checkbox>
        </Card>
        <Card size="small" title="当前解析结果">
          <p><Tag>{interaction}</Tag><Tag color="magenta">{emotion}</Tag><Tag color={blocked ? 'red' : 'default'}>{system}</Tag></p>
          <p>{blocked ? '系统覆盖层正在接管主画面。' : '当前显示交互状态，系统没有阻塞。'}</p>
        </Card>
        <Card title="4. 皮肤档案" extra={<Tag color="blue">网页预览</Tag>}>
          <p className="subtle">切换同一状态协议的视觉参数。当前选择只保存在本机并作用于模拟器，不会向真机写入。</p>
          {(session.isError || skins.isError || saveSkin.isError) && <Alert type="error" showIcon title="皮肤档案不可用" description="请确认控制台使用最新代码启动，并刷新页面。"/>}
          <Space wrap className="round-skin-actions">
            <Select aria-label="圆屏皮肤" value={selectedSkin} onChange={setSelectedSkin} style={{minWidth:220}}
              options={skins.data?.skins.map(item => ({value:item.id, label:item.name}))}/>
            <Button type="primary" loading={saveSkin.isPending} disabled={!skins.data?.enabled || selectedSkin === skins.data?.selected_skin}
              onClick={() => saveSkin.mutate(selectedSkin)}>保存预览选择</Button>
          </Space>
          {skin && <Descriptions bordered size="small" column={1} items={[
            {key:'description', label:'设计用途', children:skin.description},
            {key:'target', label:'目标画布', children:`${skin.target.board} · ${skin.target.width}×${skin.target.height} · ${skin.target.color_format}`},
            {key:'hash', label:'清单指纹', children:<code>{skin.manifest_sha256.slice(0, 16)}…</code>},
          ]}/>}<p className="subtle">皮肤不会改变交互逻辑、记忆、模型或声音。</p>
          {skins.data && !skins.data.delivery.device_apply_supported && <Alert className="settings-model-alert" type="warning" showIcon
            title="真机皮肤下发尚未开放" description="已确认原厂 assets OTA 会原地覆盖单一资源分区；需先补完整性校验、失败回退和设备回执，不能把网页选择冒充成真机切换。"/>}
        </Card>
      </section>
    </div>
  </AppShell>;
}
