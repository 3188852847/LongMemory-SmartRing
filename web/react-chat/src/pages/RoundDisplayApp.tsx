import {useEffect, useMemo, useState, type CSSProperties} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, Descriptions, Input, InputNumber, Segmented, Select, Space, Tabs, Tag} from 'antd';
import {AppShell, ConsoleNav} from '../components/AppShell';
import {useSearchParams} from 'react-router-dom';
import '../styles/display-workspace.css';
import {PageHeader} from '../components/PageHeader';
import {ApiError, ChatApi, type RoundDeviceSkin, type RoundSkin, type RoundSkinApply, type RoundSkins, type RoundWallpaperDeployment, type RoundWallpaperDeviceStatus} from '../api';
import {readRoundObservations, roundObservationKey, roundObservationStates, type RoundObservations, type RoundObservationState, writeRoundObservations} from '../features/device/roundDisplayObservations';
import {RoundWallpaperLibrary} from '../features/device/RoundWallpaperLibrary';

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
const observationNames:Record<RoundObservationState,string> = {
  idle:'待机', listening:'聆听', thinking:'思考', speaking:'说话', error:'错误',
};

const api = new ChatApi();

const devicePaletteFields = [
  ['background', '背景'], ['foreground', '主要文字'], ['muted', '次要文字'], ['accent', '待机'],
  ['listening', '聆听'], ['thinking', '思考'], ['happy', '开心'], ['concerned', '关切'], ['error', '错误'],
] as const;
type DevicePaletteKey = typeof devicePaletteFields[number][0];
type SkinDraft = {
  base_skin_id:string;
  palette:Record<DevicePaletteKey, string>;
  face:RoundSkin['face'];
};

type SkinModeSwitchState = 'idle' | 'waiting' | 'confirmed' | 'unconfirmed';

export function deviceSkinErrorCopy(error: unknown): {title:string; description:string; type:'info'|'warning'} {
  const code = error instanceof ApiError ? error.code : '';
  if (code === 'operation_busy' || code === 'control_busy') return {
    type:'info', title:'设备操作尚未结束', description:'请等待当前切换或重启完成，页面会自动刷新真机状态。',
  };
  if (code === 'device_offline' || code === 'bridge_unavailable' || code === 'bridge_timeout') return {
    type:'info', title:'圆屏当前离线', description:'设备可能仍在重启；重连后再检测即可，不能据此判断皮肤协议不可用。',
  };
  if (code === 'device_not_ready' || code === 'tools_not_ready' || code === 'device_connection_changed') return {
    type:'info', title:'圆屏正在恢复控制连接', description:'设备已经连接或正在换连接，但控制工具尚未就绪，请稍后再检测。',
  };
  return {
    type:'warning', title:'未能读取真机皮肤能力', description:'请确认圆屏在线且运行支持 skin_api=1 的固件；本次检测没有修改设备。',
  };
}

function createDraft(skin:RoundSkin):SkinDraft {
  return {
    base_skin_id:skin.id,
    palette:Object.fromEntries(devicePaletteFields.map(([key]) => [key, skin.palette[key]])) as Record<DevicePaletteKey, string>,
    face:{...skin.face},
  };
}

function skinStyle(skin?: RoundSkin): CSSProperties {
  if (!skin) return {};
  return {
    '--round-background': skin.palette.background,
    '--round-background-edge': skin.palette.background_edge,
    '--round-foreground': skin.palette.foreground,
    '--round-muted': skin.palette.muted,
    '--round-accent': skin.palette.accent,
    '--round-listening': skin.palette.listening,
    '--round-thinking': skin.palette.thinking,
    '--round-happy': skin.palette.happy,
    '--round-concerned': skin.palette.concerned,
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
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const activeTab = ['expression','skin','wallpaper','device'].includes(requestedTab ?? '') ? requestedTab! : 'expression';
  const selectTab = (tab:string) => {
    const next = new URLSearchParams(searchParams);
    if (tab === 'expression') next.delete('tab'); else next.set('tab', tab);
    setSearchParams(next);
  };
  const [interaction, setInteraction] = useState<InteractionState>('idle');
  const [emotion, setEmotion] = useState<EmotionState>('warm');
  const [system, setSystem] = useState<SystemState>('normal');
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [selectedSkin, setSelectedSkin] = useState('rose-night-v1');
  const [draft, setDraft] = useState<SkinDraft>();
  useEffect(() => {
    if (!draft) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = '';};
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [draft]);
  const [observations,setObservations] = useState<RoundObservations>({});
  const [observationNotice,setObservationNotice] = useState('');
  const [skinModeSwitch,setSkinModeSwitch] = useState<SkinModeSwitchState>('idle');
  const session = useQuery({queryKey:['round-skin-session'], queryFn:async () => {await api.bootstrap(); return true;}, staleTime:Infinity});
  const skins = useQuery({queryKey:['round-skins'], queryFn:() => api.request<RoundSkins>('/api/round-skins'), enabled:session.isSuccess});
  const wallpaperDevice = useQuery({
    queryKey:['round-wallpapers','device'],
    queryFn:()=>api.request<RoundWallpaperDeviceStatus>('/api/round-wallpapers/device'),
    enabled:session.isSuccess,
    retry:false,
    refetchInterval:skinModeSwitch === 'waiting' ? 2000 : false,
    refetchIntervalInBackground:true,
  });
  useEffect(() => {if (skins.data?.selected_skin) setSelectedSkin(skins.data.selected_skin);}, [skins.data?.selected_skin]);
  const saveSkin = useMutation({
    mutationFn:(skin_id:string) => api.request<RoundSkins>('/api/round-skins/selection', 'PUT', {skin_id}),
    onSuccess:value => skins.refetch().then(() => setSelectedSkin(value.selected_skin)),
  });
  const deviceSkin = useMutation({
    mutationFn:() => api.request<RoundDeviceSkin>('/api/round-skins/device'),
  });
  const applySkin = useMutation({
    mutationFn:(skin_id:string) => api.request<RoundSkinApply>('/api/round-skins/device', 'POST', {skin_id}),
    onSuccess:value => {if (value.verified) skins.refetch();},
  });
  const useSkinDisplay = useMutation({
    mutationFn:() => api.request<RoundWallpaperDeployment>('/api/round-wallpapers/deactivate', 'POST'),
    onMutate:() => setSkinModeSwitch('idle'),
    onSuccess:() => {
      deviceSkin.reset();
      setSkinModeSwitch('waiting');
      void queryClient.invalidateQueries({queryKey:['round-wallpapers','device']});
    },
  });
  const saveCustom = useMutation({
    mutationFn:(value:SkinDraft) => api.request<RoundSkins>('/api/round-skins/custom', 'PUT', {
      ...value,
      expected_manifest_sha256:skins.data?.skins.find(item => item.id === skins.data?.custom_skin_id)?.manifest_sha256 ?? null,
    }),
    onSuccess:value => {
      setDraft(undefined);
      skins.refetch().then(() => setSelectedSkin(value.custom_skin_id));
    },
  });
  const view = useMemo(() => resolveRoundDisplay(interaction, system), [interaction, system]);
  const skin = skins.data?.skins.find(item => item.id === selectedSkin);
  const savedSkin = skins.data?.skins.find(item => item.id === skins.data?.selected_skin);
  const deviceMatchesPreview = Boolean(!draft && deviceSkin.data && skin
    && deviceSkin.data.skin_id === skin.id
    && deviceSkin.data.manifest_sha256 === skin.manifest_sha256);
  const observationKey = deviceSkin.data
    ? roundObservationKey(deviceSkin.data.skin_id, deviceSkin.data.manifest_sha256)
    : '';
  useEffect(() => {
    setObservations(observationKey ? readRoundObservations(localStorage, observationKey) : {});
    setObservationNotice('');
  }, [observationKey]);
  useEffect(() => {
    if (skinModeSwitch !== 'waiting') return;
    const timer=window.setTimeout(() => setSkinModeSwitch('unconfirmed'), 90000);
    return () => window.clearTimeout(timer);
  }, [skinModeSwitch]);
  useEffect(() => {
    if (skinModeSwitch !== 'waiting' || !wallpaperDevice.data
        || wallpaperDevice.data.active_valid || !wallpaperDevice.data.rollback_available) return;
    setSkinModeSwitch('confirmed');
    deviceSkin.mutate();
  }, [skinModeSwitch, wallpaperDevice.data?.active_valid, wallpaperDevice.data?.rollback_available]);

  function updateObservation(state:RoundObservationState, observed?:boolean, note?:string) {
    if (!observationKey) return;
    const current=observations[state];
    const next={...observations};
    if (observed === false) delete next[state];
    else next[state]={observed_at:current?.observed_at ?? new Date().toISOString(),note:(note ?? current?.note ?? '').slice(0,160)};
    if (!writeRoundObservations(localStorage,observationKey,next)) {
      setObservationNotice('当前浏览器无法保存观察记录；页面上的勾选只在本次打开期间保留。');
    } else setObservationNotice('观察记录已保存在当前浏览器，不会写入个人记忆库。');
    setObservations(next);
  }
  const previewSkin = draft && skin ? {
    ...skin, palette:{...skin.palette, ...draft.palette}, face:draft.face,
  } : skin;
  const blocked = Boolean(systemCopy[system]);
  const powerLabel = system === 'charging' ? '充电中' : system === 'low_battery' ? '电量低' : '';
  const sidebar = <ConsoleNav active="display" legacyPath="/"/>;

  return <AppShell subtitle="智能圆屏交互实验台" className="display-preview-shell" sidebar={sidebar}>
    <PageHeader eyebrow="体验设计" title="圆屏状态预览" description="在电脑上编辑并预览，再单独检测与下发真机。网页动画、皮肤回读和实机观察分别核对。"/>

    <div className="display-preview-layout">
      <section className="display-stage" aria-label="圆屏模拟画布">
        <div className="display-preview-caption"><h2>{activeTab === 'wallpaper' ? '电脑皮肤预览' : '电脑预览'}</h2><Tag color={draft ? 'gold' : 'blue'}>{draft ? '未保存草稿' : '预览选择'}</Tag></div>
        <div style={skinStyle(previewSkin)} className={`round-display tone-${view.tone} state-${interaction} emotion-${emotion} focus-${view.focus}`}>
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
        <p className="display-preview-caption">{previewSkin?.name ?? selectedSkin} · {view.title}</p>
        <small>画布：360 × 360 px · 中央安全区：约 255 × 255 px</small>
        <p className="subtle">{activeTab === 'wallpaper' ? '壁纸预览在素材列表中；这张画布仍显示几何皮肤。' : '编辑会更新电脑画布；保存和真机下发各需单独操作。'}网页动画不证明新固件已在真机运行。</p>
      </section>
      <section className="display-controls" aria-label="预览控制">
        <Tabs className="display-task-tabs" activeKey={activeTab} onChange={selectTab} items={[
          {key:'expression', label:'表情', children:<div className="display-task-content">
        <Card title="交互阶段"><p className="subtle">描述系统正在做什么，是圆屏的主状态。</p>
          <Segmented block options={interactionOptions} value={interaction} onChange={value => setInteraction(value as InteractionState)}/>
        </Card>
        <Card title="情绪表达"><p className="subtle">只改变眼神、颜色和动作幅度，不改变交互逻辑。</p>
          <Segmented block options={emotionOptions} value={emotion} onChange={value => setEmotion(value as EmotionState)}/>
        </Card>
        <Card title="系统覆盖"><p className="subtle">阻塞性故障会盖过“聆听/思考/说话”；充电和低电量只显示边缘提示。</p>
          <Select className="wide" aria-label="系统状态" value={system} options={systemOptions} onChange={setSystem}/>
          <Checkbox checked={showSafeArea} onChange={event => setShowSafeArea(event.target.checked)}>显示约 255×255 中央安全区</Checkbox>
        </Card>
        <Card size="small" title="当前解析结果">
          <p><Tag>{interaction}</Tag><Tag color="magenta">{emotion}</Tag><Tag color={blocked ? 'red' : 'default'}>{system}</Tag></p>
          <p>{blocked ? '系统覆盖层正在接管主画面。' : '当前显示交互状态，系统没有阻塞。'}</p>
        </Card>
          </div>},
          {key:'skin', label:'皮肤', children:<div className="display-task-content">
        <Card title="皮肤档案" extra={<Tag color="blue">skin_api=1</Tag>}>
          <p className="subtle">选择只更新电脑预览。“保存预览选择”保留下次打开的默认值；编辑草稿需另存自定义皮肤。真机检测和下发在“实机验证”分类。</p>
          <Descriptions className="round-skin-state-map" bordered size="small" column={1} items={[
            {key:'working',label:'当前编辑/预览',children:<><strong>{skin?.name ?? selectedSkin}</strong><br/><Tag color={draft?'gold':'blue'}>{draft?'未保存编辑草稿':'已加载档案'}</Tag></>},
            {key:'saved',label:'网页保存选择',children:<><strong>{savedSkin?.name ?? skins.data?.selected_skin ?? '读取中'}</strong><br/><Tag>只影响预览默认值</Tag></>},
          ]}/>
          {(session.isError || skins.isError || saveSkin.isError) && <Alert type="error" showIcon title="皮肤档案不可用" description="请确认控制台使用最新代码启动，并刷新页面。"/>}
          <Space wrap className="round-skin-actions">
            <Select disabled={Boolean(draft) || saveCustom.isPending} aria-label="圆屏皮肤" value={selectedSkin} onChange={value => {setSelectedSkin(value); setDraft(undefined);}} style={{minWidth:220}}
              options={skins.data?.skins.map(item => ({value:item.id, label:item.name}))}/>
            <Button type="primary" loading={saveSkin.isPending} disabled={!skins.data?.enabled || Boolean(draft) || selectedSkin === skins.data?.selected_skin}
              onClick={() => saveSkin.mutate(selectedSkin)}>保存预览选择</Button>
            <Button disabled={!skin || Boolean(draft)} onClick={() => skin && setDraft(createDraft(skin))}>从当前皮肤开始编辑</Button>
          </Space>
          {skin && <Descriptions bordered size="small" column={1} items={[
            {key:'description', label:'设计用途', children:skin.description},
            {key:'target', label:'目标画布', children:`${skin.target.board} · ${skin.target.width}×${skin.target.height} · ${skin.target.color_format}`},
            {key:'hash', label:'清单指纹', children:<code>{skin.manifest_sha256.slice(0, 16)}…</code>},
          ]}/>}<p className="subtle">皮肤不会改变交互逻辑、记忆、模型或声音。</p>
          {saveSkin.isSuccess && !draft && <p role="status">电脑预览选择已保存；真机尚未下发。</p>}
          {draft && <div className="round-skin-editor" role="region" aria-label="本机自定义皮肤编辑器">
            <h3>我的自定义皮肤</h3>
            <p className="subtle">修改会立即出现在左侧预览；保存后生成新的 SHA-256，但不会自动写入圆屏。取消或保存编辑后才能切换皮肤。</p>
            <div className="round-skin-color-grid">
              {devicePaletteFields.map(([key, label]) => <label key={key}>
                <span>{label}</span>
                <input type="color" disabled={saveCustom.isPending} aria-label={`皮肤颜色：${label}`} value={draft.palette[key]}
                  onChange={event => setDraft(current => current ? {
                    ...current, palette:{...current.palette, [key]:event.target.value.toUpperCase()},
                  } : current)}/>
                <code>{draft.palette[key]}</code>
              </label>)}
            </div>
            <div className="round-skin-size-grid">
              {([['eye_width', '眼睛宽度', 12, 36], ['eye_height', '眼睛高度', 18, 48], ['mouth_width', '嘴部宽度', 20, 64]] as const)
                .map(([key, label, min, max]) => <label key={key}><span>{label}</span>
                  <InputNumber disabled={saveCustom.isPending} aria-label={label} min={min} max={max} value={draft.face[key]}
                    onChange={value => typeof value === 'number' && setDraft(current => current ? {
                      ...current, face:{...current.face, [key]:value},
                    } : current)}/>
                </label>)}
            </div>
            <Space wrap>
              <Button type="primary" loading={saveCustom.isPending} onClick={() => saveCustom.mutate(draft)}>保存为“我的自定义皮肤”</Button>
              <Button disabled={saveCustom.isPending} onClick={() => setDraft(undefined)}>取消编辑</Button>
            </Space>
            {saveCustom.isError && <Alert className="settings-model-alert" type="warning" showIcon
              title="自定义皮肤没有保存" description="可能有另一个页面先修改了档案。刷新页面后重新编辑，旧草稿不会覆盖新版本。"/>}
          </div>}
          <Alert className="settings-model-alert" type="warning" showIcon title="没有改写 assets 分区"
            description="首版只修改固定 LVGL 参数并保留内置默认值；图片资源、浏览器动画和背景边缘渐变仍不下发。"/>
        </Card>
          </div>},
          {key:'wallpaper', label:'壁纸', children:<div className="display-task-content">
        <RoundWallpaperLibrary api={api} sessionReady={session.isSuccess}/>
          </div>},
          {key:'device', label:'实机验证', children:<div className="display-task-content">
        <Card title="真机检测与下发">
          <p><strong>将要下发：{skin?.name ?? selectedSkin}</strong>。电脑选择、保存档案和设备写入是三个动作。下发仅使用已保存的皮肤；有编辑草稿时请先保存或取消。</p>
          <Descriptions bordered size="small" column={1} items={[
            {key:'device',label:'最近真机回读',children:deviceSkin.isSuccess
              ? <><strong>{deviceSkin.data.skin_id}</strong><br/><Tag color={deviceMatchesPreview?'success':'warning'}>{deviceMatchesPreview?'与当前预览一致':'与当前预览不同'}</Tag></>
              : <><strong>尚未读取</strong><br/><Tag>不会自动检测</Tag></>},
            {key:'mode',label:'真机显示模式',children:wallpaperDevice.isSuccess
              ? <><strong>{wallpaperDevice.data.active_valid?'动态壁纸':'几何皮肤'}</strong><br/><Tag color={wallpaperDevice.data.active_valid?'gold':'success'}>{wallpaperDevice.data.active_valid?'皮肤当前被覆盖':'皮肤可以显示'}</Tag></>
              : <><strong>尚未读取</strong><br/><Tag>圆屏在线后刷新</Tag></>},
          ]}/>
          <Space wrap className="round-skin-actions">
            <Button loading={deviceSkin.isPending} disabled={skinModeSwitch === 'waiting'} onClick={() => deviceSkin.mutate()}>检测真机皮肤能力</Button>
            <Button danger loading={applySkin.isPending} disabled={!deviceSkin.isSuccess || !skin || Boolean(draft)}
              onClick={() => applySkin.mutate(selectedSkin)}>应用到真机</Button>
            <Button loading={useSkinDisplay.isPending} disabled={!wallpaperDevice.data?.active_valid || skinModeSwitch === 'waiting'}
              onClick={() => useSkinDisplay.mutate()}>{skinModeSwitch === 'waiting' ? '等待圆屏重连' : '切换为皮肤显示（会重启）'}</Button>
          </Space>
          {deviceSkin.isSuccess && (
            <Alert className="settings-model-alert" type="success" showIcon
              title={`真机支持皮肤协议，当前为 ${deviceSkin.data.skin_id}`}
              description={`设备清单指纹：${deviceSkin.data.manifest_sha256.slice(0, 16)}…`}/>
          )}
          {deviceSkin.isError && (() => {const copy=deviceSkinErrorCopy(deviceSkin.error); return <Alert className="settings-model-alert" type={copy.type} showIcon
            title={copy.title} description={copy.description}/>;})()}
          {applySkin.isSuccess && (
            <Alert className="settings-model-alert" type={applySkin.data.verified ? (wallpaperDevice.data?.active_valid?'warning':'success') : 'error'} showIcon
              title={applySkin.data.verified ? (wallpaperDevice.data?.active_valid?'皮肤参数已写入，但动态壁纸仍在显示':'真机皮肤已写入并通过回读核对') : '设备已应答，但回读核对未通过'}
              description={applySkin.data.verified ? (wallpaperDevice.data?.active_valid?'点击“切换为皮肤显示”后设备会重启；壁纸槽仍保留，可随时恢复。':'重启后设备会从 NVS 恢复同一皮肤。') : `原因：${applySkin.data.reason ?? 'readback_mismatch'}`}/>
          )}
          {applySkin.isError && <Alert className="settings-model-alert" type="error" showIcon title="真机皮肤写入失败" description="未把本机选择冒充成设备成功；请先重新检测设备能力。"/>}
          {useSkinDisplay.isSuccess && skinModeSwitch === 'waiting' && <Alert className="settings-model-alert" type="info" showIcon
            title="切换指令已发送，正在等待圆屏重连" description="提交已经结束；页面会自动只读检查显示模式，不会重复发送切换或重启指令。"/>}
          {useSkinDisplay.isSuccess && skinModeSwitch === 'confirmed' && <Alert className="settings-model-alert" type="success" showIcon
            title="已确认切换为皮肤显示" description="圆屏重连后的状态表明动态壁纸已停用；皮肤能力也已自动重新检测。"/>}
          {useSkinDisplay.isSuccess && skinModeSwitch === 'unconfirmed' && <Alert className="settings-model-alert" type="warning" showIcon
            title="切换指令已发送，但尚未确认重连状态" description="设备可能仍离线；页面没有重复执行写入或重启，圆屏在线后可刷新状态。"/>}
          {useSkinDisplay.isError && <Alert className="settings-model-alert" type="error" showIcon
            title="未能切换为皮肤显示" description="请确认圆屏在线且运行支持显示模式切换的新固件；不会删除现有壁纸。"/>}
        </Card>
        <Card title="真机五态观察" extra={<Tag color={roundObservationStates.every(state=>observations[state])?'success':'default'}>
          {roundObservationStates.filter(state=>observations[state]).length} / {roundObservationStates.length}
        </Tag>}>
          <p className="subtle">这里只记录你亲眼看到的真机表现，不从网页预览或设备在线状态自动判定。记录按真机皮肤 ID 和清单指纹隔离，只保存在当前浏览器。</p>
          {!deviceSkin.isSuccess && <Alert type="info" showIcon title="先检测真机皮肤能力" description="取得真机回读的皮肤 ID 与清单指纹后，才能记录对应版本的观察结果。"/>}
          {deviceSkin.isSuccess && <div className="round-observation-list">
            {roundObservationStates.map(state=><div className="round-observation-row" key={state}>
              <Checkbox checked={Boolean(observations[state])} onChange={event=>updateObservation(state,event.target.checked)}>{observationNames[state]}</Checkbox>
              <Input aria-label={`${observationNames[state]}观察备注`} maxLength={160} disabled={!observations[state]}
                placeholder="可选：记录裁切、文字或动画问题" value={observations[state]?.note ?? ''}
                onChange={event=>updateObservation(state,true,event.target.value)}/>
              <small>{observations[state]?.observed_at ? new Date(observations[state]!.observed_at).toLocaleString('zh-CN') : '尚未观察'}</small>
            </div>)}
          </div>}
          {observationNotice&&<Alert className="settings-model-alert" type="info" showIcon title={observationNotice}/>}
        </Card>
          </div>},
        ]}/>
      </section>
    </div>
  </AppShell>;
}
