import {useQuery} from '@tanstack/react-query';
import {Alert, Card, Tag} from 'antd';
import {Link} from 'react-router-dom';
import {ChatApi, type Config, type DeviceStatus, type MemoryPageSummary, type RuntimeStatus} from './api';
import {AppShell, ConsoleNav} from './AppShell';
import {ConsoleStatusRail} from './ChatObservability';
import {PageHeader} from './PageHeader';
import {SystemDiagnostics} from './SystemDiagnostics';

const api = new ChatApi();

function modelSummary(config?: Config) {
  if (!config?.enabled) return {tone: 'default', label: '聊天未启用', detail: '通过启动面板启用文字服务后再核对模型。'};
  if (config.provider === 'fake') return {tone: 'default', label: 'Fake 工程替身', detail: '只验证工程流程，不具备真实回答能力。'};
  if (config.model_health?.state === 'available') return {tone: 'green', label: '最近验证可用', detail: `${config.model} · ${config.provider}`};
  if (config.model_health?.state === 'unavailable') return {tone: 'red', label: '最近验证失败', detail: '到“设置中心 → 模型与服务”查看固定故障类别。'};
  return {tone: 'gold', label: '尚未验证', detail: '服务已装配不等于模型网络和 Key 当前有效。'};
}

function serviceLabel(state?: string) {
  return ({ready:'已就绪', running:'进程运行中', disabled:'本次未启用', exited:'进程已退出'} as Record<string,string>)[state ?? ''] ?? '状态未知';
}

function runtimeTone(state?: string) {
  if (state === 'ready') return 'green';
  if (state === 'failed' || state === 'stale') return 'red';
  return 'gold';
}

/**
 * 系统总览只组合已有只读接口。它不启动服务、不调用模型，也不把历史状态
 * 冒充实时健康；每张卡片都把用户带到负责该事实的页面继续处理。
 */
export function OverviewApp() {
  const session = useQuery({
    queryKey: ['overview-session'],
    queryFn: async () => { await api.bootstrap(); return true; },
    staleTime: Infinity,
  });
  const config = useQuery({
    queryKey: ['chat-config'], queryFn: () => api.request<Config>('/api/chat-config'),
    enabled: session.isSuccess, retry: false,
  });
  const device = useQuery({
    queryKey: ['device-status'], queryFn: () => api.request<DeviceStatus>('/api/device'),
    enabled: session.isSuccess, retry: false, refetchInterval: 5000,
  });
  const memories = useQuery({
    queryKey: ['overview-active-memory-count'],
    queryFn: () => api.request<MemoryPageSummary>('/api/memories?q=&state=active&offset=0&limit=1'),
    enabled: session.isSuccess && config.data?.enabled === true, retry: false, staleTime: 30000,
  });
  const runtime = useQuery({
    queryKey: ['runtime-status'], queryFn: () => api.request<RuntimeStatus>('/api/runtime-status'),
    enabled: session.isSuccess, retry: false, refetchInterval: 2000,
  });
  const model = modelSummary(config.data);
  const consoleReady = session.isSuccess && config.isSuccess;

  return <AppShell subtitle="本机陪伴系统概览" className="overview-shell" sidebar={<ConsoleNav active="overview" legacyPath="/chat"/>}>
    <PageHeader eyebrow="日常使用" title="系统总览" description="先看哪些链路真正可用，再进入聊天、记忆、设备或设置；本页只读取状态，不会调用模型或改变圆屏。"
      action={<span className="overview-refresh-note">圆屏每 5 秒核对一次</span>}/>
    {session.isError && <Alert type="error" showIcon title="控制台会话不可用" description="网页后端可能已经停止。请回到启动面板查看受管服务状态；本页没有自动重启任何进程。"/>}
    <ConsoleStatusRail config={config.data} device={device.data} deviceFailed={device.isError} activeMemoryCount={memories.data?.total}/>
    <section className="overview-grid" aria-label="系统入口与说明">
      <SystemDiagnostics runtime={runtime.data} config={config.data} device={device.data}
        failures={{runtime:runtime.isError,config:config.isError,device:device.isError}}/>
      <Card className="overview-runtime-card" title="受管服务"
        extra={<Tag color={runtimeTone(runtime.data?.state)}>{runtime.data?.state === 'ready' ? '启动面板在线' : runtime.data?.state === 'stale' ? '状态已过期' : runtime.data?.enabled === false ? '非启动面板模式' : '正在核对'}</Tag>}>
        <dl className="overview-facts">
          <div><dt>网页控制台</dt><dd>{serviceLabel(runtime.data?.services.console)}</dd></div>
          <div><dt>小智语音</dt><dd>{serviceLabel(runtime.data?.services.voice)}</dd></div>
          <div><dt>VoxCPM2</dt><dd>{serviceLabel(runtime.data?.services.voxcpm2)}</dd></div>
          <div><dt>sanoTTS</dt><dd>{serviceLabel(runtime.data?.services.sanotts)}</dd></div>
          <div><dt>CosyVoice 3</dt><dd>{serviceLabel(runtime.data?.services.cosyvoice3)}</dd></div>
          <div><dt>状态新鲜度</dt><dd>{runtime.data?.age_seconds !== undefined ? `${runtime.data.age_seconds.toFixed(1)} 秒前` : '不可用'}</dd></div>
        </dl>
        <p className="subtle">这里只显示启动面板拥有的进程；手动终端启动会标为“非启动面板模式”。进程运行不代表模型、设备或声音已经可用，请结合下方独立状态判断。</p>
      </Card>
      <Card title="开始使用" extra={<Tag color={consoleReady ? 'green' : 'gold'}>{consoleReady ? '控制台就绪' : '正在核对'}</Tag>}>
        <div className="overview-actions">
          <Link to="/chat-react"><strong>文字聊天</strong><span>输入、回答和本轮记忆证据</span></Link>
          <Link to="/device"><strong>设备与状态</strong><span>圆屏连接、音量、亮度和快照</span></Link>
          <Link to="/memories"><strong>记忆管理</strong><span>L0 原话、L1 事实、纠正与删除</span></Link>
          <Link to="/display-preview"><strong>圆屏外观</strong><span>状态视觉、皮肤与动态壁纸</span></Link>
        </div>
      </Card>
      <Card title="当前回答链路" extra={<Tag color={model.tone}>{model.label}</Tag>}>
        <dl className="overview-facts">
          <div><dt>模型</dt><dd>{config.data?.model ?? '未知'}</dd></div>
          <div><dt>记忆方法</dt><dd>{config.data?.method ?? '未装配'}</dd></div>
          <div><dt>召回策略</dt><dd>{config.data?.retrieval === 'keyword_dense_rrf_v1' ? '关键词＋本地向量' : config.data?.retrieval ? '关键词基线' : '未装配'}</dd></div>
          <div><dt>有效 L1</dt><dd>{memories.data ? `${memories.data.total} 条` : config.data?.enabled ? '读取中或不可用' : '聊天未启用'}</dd></div>
        </dl>
        <p className="subtle">{model.detail}</p>
        <Link className="overview-detail-link" to="/settings?tab=model">打开模型与服务诊断</Link>
      </Card>
      <Card title="当前圆屏链路" extra={<Tag color={device.isError ? 'red' : device.data?.ready ? 'green' : 'gold'}>{device.isError ? '状态未知' : device.data?.ready ? '已连接' : '等待圆屏'}</Tag>}>
        <dl className="overview-facts">
          <div><dt>活动连接</dt><dd>{device.data?.connection_count ?? '未知'}</dd></div>
          <div><dt>设备快照</dt><dd>{device.data?.read_status_supported ? '可读取' : '当前不可读取'}</dd></div>
          <div><dt>音量控制</dt><dd>{device.data?.set_volume_supported ? '可用' : '当前不可用'}</dd></div>
          <div><dt>AEC 声明</dt><dd>{device.data?.aec_advertised ? '固件已上报' : '未上报或未知'}</dd></div>
        </dl>
        <p className="subtle">小智进程存在不等于圆屏已连接；最终以当前活动连接和设备工具回执为准。</p>
        <Link className="overview-detail-link" to="/device">打开设备诊断</Link>
      </Card>
      <Card title="配置与研究入口">
        <div className="overview-actions compact">
          <Link to="/settings"><strong>设置中心</strong><span>模型、记忆后端、角色、声音、外观与主动交流</span></Link>
          <Link to="/memory-quality"><strong>记忆质量</strong><span>漏记、错记和召回问题样本</span></Link>
          <Link to="/experiments-react"><strong>实验中心</strong><span>冻结对照、运行预算和逐题复核</span></Link>
        </div>
      </Card>
    </section>
  </AppShell>;
}
