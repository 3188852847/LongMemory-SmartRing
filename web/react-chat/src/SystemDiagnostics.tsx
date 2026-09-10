import {Alert, Card, Tag} from 'antd';
import {Link} from 'react-router-dom';
import type {Config, DeviceStatus, RuntimeStatus} from './api';

export interface DiagnosticFinding {
  code:string;
  tone:'error'|'warning'|'info'|'success';
  title:string;
  detail:string;
  path?:string;
  action?:string;
}

/**
 * 诊断只组合已经读取到的事实，不主动探测外网或圆屏，也不把“未启用”
 * 当成故障。稳定 code 便于以后记录真实故障频率而不保存私密正文。
 */
export function diagnoseSystem(runtime?:RuntimeStatus, config?:Config, device?:DeviceStatus,
  failures:{runtime?:boolean;config?:boolean;device?:boolean} = {}):DiagnosticFinding[] {
  const items:DiagnosticFinding[] = [];
  if (failures.runtime) items.push({code:'runtime_status_unreadable',tone:'warning',title:'无法读取启动面板状态',detail:'控制台仍可使用，但无法判断语音和本地声音进程是否由当前启动面板管理。'});
  else if (runtime?.state === 'stale') items.push({code:'launcher_status_stale',tone:'error',title:'启动面板状态已经过期',detail:'不要依据旧状态判断服务正常；请查看启动面板是否仍在运行。'});
  else if (runtime?.enabled === false) items.push({code:'manual_console_start',tone:'info',title:'当前不是统一启动模式',detail:'控制台可能由终端手动启动，因此无法汇总小智语音与 VoxCPM2 进程。'});

  if (failures.config) items.push({code:'chat_config_unreadable',tone:'error',title:'回答配置读取失败',detail:'当前无法确认回答模型与记忆方法。请刷新；不要据此重复提交聊天。',path:'/settings?tab=model',action:'打开模型设置'});
  else if (config?.enabled && config.model_health?.state === 'unavailable') items.push({code:'answer_model_unavailable',tone:'error',title:'回答模型最近验证失败',detail:'这通常会导致“小智忙”或文字回答失败；查看固定故障类别并更新对应配置。',path:'/settings?tab=model',action:'查看模型诊断'});
  else if (config?.enabled && config.model_health?.state === 'unchecked') items.push({code:'answer_model_unchecked',tone:'warning',title:'回答模型尚未验证',detail:'配置已加载不代表 Key、网络和服务端当前可用。',path:'/settings?tab=model',action:'检测模型'});

  if (failures.device) items.push({code:'device_status_unreadable',tone:'warning',title:'圆屏状态读取失败',detail:'没有向设备发送重试命令；请到设备页核对控制桥。',path:'/device',action:'打开设备诊断'});
  else if (runtime?.services.voice === 'running' && device && !device.ready) items.push({code:'voice_running_device_offline',tone:'warning',title:'小智进程运行，但圆屏未连接',detail:'先核对圆屏网络与 OTA/WebSocket 地址；无需重新启动文字控制台。',path:'/device',action:'核对圆屏连接'});

  if (runtime?.services.voxcpm2 === 'running') items.push({code:'voxcpm_loading',tone:'info',title:'VoxCPM2 进程仍在加载',detail:'本地模型进程存在，但健康检查尚未通过；首次载入权重可能需要等待。',path:'/settings?tab=voice',action:'查看声音设置'});
  if (items.length === 0 && runtime?.state === 'ready' && config?.model_health?.state === 'available' && device?.ready) {
    items.push({code:'observed_paths_ready',tone:'success',title:'当前可观测链路正常',detail:'启动器、回答模型和圆屏连接均有当前证据；这不等于回答质量或设备播放效果已经验收。'});
  }
  return items;
}

export function SystemDiagnostics(props:{runtime?:RuntimeStatus;config?:Config;device?:DeviceStatus;failures?:{runtime?:boolean;config?:boolean;device?:boolean}}) {
  const items = diagnoseSystem(props.runtime, props.config, props.device, props.failures);
  return <Card className="overview-diagnostics-card" title="当前诊断"
    extra={<Tag color={items.some(x => x.tone === 'error') ? 'red' : items.some(x => x.tone === 'warning') ? 'gold' : 'cyan'}>{items.length} 项结论</Tag>}>
    <div className="overview-diagnostics-list">
      {items.length === 0 && <Alert type="info" showIcon title="暂无可判断结论" description="状态仍在读取，或当前模式没有足够事实。"/>}
      {items.map(item => <Alert key={item.code} type={item.tone} showIcon title={item.title}
        description={<span>{item.detail}{item.path && <Link to={item.path}>{item.action}</Link>}</span>}/>) }
    </div>
  </Card>;
}
