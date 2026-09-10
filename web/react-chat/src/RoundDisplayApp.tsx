import {useEffect, useMemo, useState, type CSSProperties} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Alert, Button, Card, Checkbox, Descriptions, Input, InputNumber, Segmented, Select, Space, Tag} from 'antd';
import {AppShell, ConsoleNav} from './AppShell';
import {PageHeader} from './PageHeader';
import {ChatApi, type RoundDeviceSkin, type RoundSkin, type RoundSkinApply, type RoundSkins} from './api';
import {readRoundObservations, roundObservationKey, roundObservationStates, type RoundObservations, type RoundObservationState, writeRoundObservations} from './roundDisplayObservations';
import {RoundWallpaperLibrary} from './RoundWallpaperLibrary';

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
  const [interaction, setInteraction] = useState<InteractionState>('idle');
  const [emotion, setEmotion] = useState<EmotionState>('warm');
  const [system, setSystem] = useState<SystemState>('normal');
  const [showSafeArea, setShowSafeArea] = useState(false);
  const [selectedSkin, setSelectedSkin] = useState('rose-night-v1');
  const [draft, setDraft] = useState<SkinDraft>();
  const [observations,setObservations] = useState<RoundObservations>({});
  const [observationNotice,setObservationNotice] = useState('');
  const session = useQuery({queryKey:['round-skin-session'], queryFn:async () => {await api.bootstrap(); return true;}, staleTime:Infinity});
  const skins = useQuery({queryKey:['round-skins'], queryFn:() => api.request<RoundSkins>('/api/round-skins'), enabled:session.isSuccess});
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
  const deviceMatchesPreview = Boolean(deviceSkin.data && skin
    && deviceSkin.data.skin_id === skin.id
    && deviceSkin.data.manifest_sha256 === skin.manifest_sha256);
  const observationKey = deviceSkin.data
    ? roundObservationKey(deviceSkin.data.skin_id, deviceSkin.data.manifest_sha256)
    : '';
  useEffect(() => {
    setObservations(observationKey ? readRoundObservations(localStorage, observationKey) : {});
    setObservationNotice('');
  }, [observationKey]);

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
  const sidebar = <><ConsoleNav active="display" legacyPath="/"/><Card size="small" title="实现边界">
    <p>网页完整预览 360×360 状态协议；真机首版只下发颜色与脸部尺寸，不下发浏览器动画或渐变资源。</p>
  </Card></>;

  return <AppShell subtitle="智能圆屏交互实验台" className="display-preview-shell" sidebar={sidebar}>
    <PageHeader eyebrow="体验设计" title="圆屏状态预览" description="先验证待机、聆听、思考、回应和异常是否一眼可辨，再把稳定协议接入真实固件。" meta="画布：360 × 360 px · 中央安全区：约 255 × 255 px"/>
    <Alert type="info" showIcon title="预览与真机采用同一版皮肤清单" description="交互状态决定主体表达；真机写入必须手动触发，并在固件回读的皮肤 ID、清单指纹和全部支持字段一致后才显示成功。"/>
    <div className="display-preview-layout">
      <section className="display-stage" aria-label="圆屏模拟画布">
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
        <Card title="4. 皮肤档案" extra={<Tag color="blue">skin_api=1</Tag>}>
          <p className="subtle">“保存预览选择”只改网页；“应用到真机”会写入设备 NVS 并立即回读核对。语言模型看不到这两个固件管理工具。</p>
          <Descriptions className="round-skin-state-map" bordered size="small" column={{xs:1,sm:1,md:3}} items={[
            {key:'working',label:'当前编辑/预览',children:<><strong>{skin?.name ?? selectedSkin}</strong><br/><Tag color={draft?'gold':'blue'}>{draft?'未保存编辑草稿':'已加载档案'}</Tag></>},
            {key:'saved',label:'网页保存选择',children:<><strong>{savedSkin?.name ?? skins.data?.selected_skin ?? '读取中'}</strong><br/><Tag>只影响预览默认值</Tag></>},
            {key:'device',label:'最近真机回读',children:deviceSkin.isSuccess
              ? <><strong>{deviceSkin.data.skin_id}</strong><br/><Tag color={deviceMatchesPreview?'success':'warning'}>{deviceMatchesPreview?'与当前预览一致':'与当前预览不同'}</Tag></>
              : <><strong>尚未读取</strong><br/><Tag>不会自动检测</Tag></>},
          ]}/>
          {(session.isError || skins.isError || saveSkin.isError) && <Alert type="error" showIcon title="皮肤档案不可用" description="请确认控制台使用最新代码启动，并刷新页面。"/>}
          <Space wrap className="round-skin-actions">
            <Select aria-label="圆屏皮肤" value={selectedSkin} onChange={value => {setSelectedSkin(value); setDraft(undefined);}} style={{minWidth:220}}
              options={skins.data?.skins.map(item => ({value:item.id, label:item.name}))}/>
            <Button type="primary" loading={saveSkin.isPending} disabled={!skins.data?.enabled || selectedSkin === skins.data?.selected_skin}
              onClick={() => saveSkin.mutate(selectedSkin)}>保存预览选择</Button>
            <Button loading={deviceSkin.isPending} onClick={() => deviceSkin.mutate()}>检测真机皮肤能力</Button>
            <Button danger loading={applySkin.isPending} disabled={!deviceSkin.isSuccess || !skin}
              onClick={() => applySkin.mutate(selectedSkin)}>应用到真机</Button>
            <Button disabled={!skin} onClick={() => skin && setDraft(createDraft(skin))}>从当前皮肤开始编辑</Button>
          </Space>
          {skin && <Descriptions bordered size="small" column={1} items={[
            {key:'description', label:'设计用途', children:skin.description},
            {key:'target', label:'目标画布', children:`${skin.target.board} · ${skin.target.width}×${skin.target.height} · ${skin.target.color_format}`},
            {key:'hash', label:'清单指纹', children:<code>{skin.manifest_sha256.slice(0, 16)}…</code>},
          ]}/>}<p className="subtle">皮肤不会改变交互逻辑、记忆、模型或声音。</p>
          {deviceSkin.isSuccess && (
            <Alert className="settings-model-alert" type="success" showIcon
              title={`真机支持皮肤协议，当前为 ${deviceSkin.data.skin_id}`}
              description={`设备清单指纹：${deviceSkin.data.manifest_sha256.slice(0, 16)}…`}/>
          )}
          {deviceSkin.isError && <Alert className="settings-model-alert" type="warning" showIcon
            title="当前真机没有响应皮肤协议" description="旧固件、设备离线或小智控制桥未更新都会出现此结果；不会自动写入或重试。"/>}
          {applySkin.isSuccess && (
            <Alert className="settings-model-alert" type={applySkin.data.verified ? 'success' : 'error'} showIcon
              title={applySkin.data.verified ? '真机皮肤已写入并通过回读核对' : '设备已应答，但回读核对未通过'}
              description={applySkin.data.verified ? '重启后设备会从 NVS 恢复同一皮肤。' : `原因：${applySkin.data.reason ?? 'readback_mismatch'}`}/>
          )}
          {applySkin.isError && <Alert className="settings-model-alert" type="error" showIcon title="真机皮肤写入失败" description="未把本机选择冒充成设备成功；请先重新检测设备能力。"/>}
          {draft && <div className="round-skin-editor" role="region" aria-label="本机自定义皮肤编辑器">
            <h3>我的自定义皮肤</h3>
            <p className="subtle">修改会立即出现在左侧预览；保存后生成新的 SHA-256，但不会自动写入圆屏。</p>
            <div className="round-skin-color-grid">
              {devicePaletteFields.map(([key, label]) => <label key={key}>
                <span>{label}</span>
                <input type="color" aria-label={`皮肤颜色：${label}`} value={draft.palette[key]}
                  onChange={event => setDraft(current => current ? {
                    ...current, palette:{...current.palette, [key]:event.target.value.toUpperCase()},
                  } : current)}/>
                <code>{draft.palette[key]}</code>
              </label>)}
            </div>
            <div className="round-skin-size-grid">
              {([['eye_width', '眼睛宽度', 12, 36], ['eye_height', '眼睛高度', 18, 48], ['mouth_width', '嘴部宽度', 20, 64]] as const)
                .map(([key, label, min, max]) => <label key={key}><span>{label}</span>
                  <InputNumber aria-label={label} min={min} max={max} value={draft.face[key]}
                    onChange={value => typeof value === 'number' && setDraft(current => current ? {
                      ...current, face:{...current.face, [key]:value},
                    } : current)}/>
                </label>)}
            </div>
            <Space wrap>
              <Button type="primary" loading={saveCustom.isPending} onClick={() => saveCustom.mutate(draft)}>保存为“我的自定义皮肤”</Button>
              <Button onClick={() => setDraft(undefined)}>取消编辑</Button>
            </Space>
            {saveCustom.isError && <Alert className="settings-model-alert" type="warning" showIcon
              title="自定义皮肤没有保存" description="可能有另一个页面先修改了档案。刷新页面后重新编辑，旧草稿不会覆盖新版本。"/>}
          </div>}
          <Alert className="settings-model-alert" type="warning" showIcon title="没有改写 assets 分区"
            description="首版只修改固定 LVGL 参数并保留内置默认值；图片资源、浏览器动画和背景边缘渐变仍不下发。"/>
        </Card>
        <Card title="5. 真机五态观察" extra={<Tag color={roundObservationStates.every(state=>observations[state])?'success':'default'}>
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
        <RoundWallpaperLibrary api={api} sessionReady={session.isSuccess}/>
      </section>
    </div>
  </AppShell>;
}
