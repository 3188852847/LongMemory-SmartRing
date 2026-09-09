import {ApiError} from './api';
import {modelFailure} from './modelHealth';

export type SettingsFailurePhase = 'read' | 'write';

/** 设置中心只解释受控错误类别；未知异常不回显路径、配置正文或密钥。 */
const settingsFailureText: Record<string, string> = {
  session_required: '网页会话已失效，请刷新整个页面。没有自动重发设置操作。',
  csrf_rejected: '请求校验失败，请刷新整个页面。没有自动重发设置操作。',
  origin_rejected: '当前访问地址不符合本机安全限制。请从启动面板重新打开控制台。',
  runtime_auth_required: '本机控制台认证尚未建立。请从启动面板重新打开控制台。',
  request_rejected: '本机服务拒绝了该请求。请刷新页面后核对当前状态。',
  model_profiles_disabled: '当前启动方式没有开放模型配置档管理。请从统一启动面板进入。',
  invalid_model_profile: '模型配置无效。请核对服务根地址、模型名、超时、输出上限以及 HTTP 风险开关。',
  voice_model_profiles_disabled: '圆屏模型配置管理未启用。请核对启动面板中的小智服务目录。',
  invalid_voice_model_profile: '圆屏模型配置档无效；没有改变下次启动选择。',
  voice_model_check_busy: '另一项圆屏模型检测仍在进行。本次没有启动重复检测。',
  chat_disabled: '文字服务尚未启用，当前不能读取或保存助手角色。',
  role_conflict: '助手角色已在另一个页面改变。为避免覆盖较新版本，请重新读取后再编辑。',
  invalid_role: '助手角色内容无效。请核对名称、完整提示词和结构化偏好。',
  role_storage_unavailable: '暂时无法访问助手角色配置。请不要重复保存，先确认控制台和记忆库仍可用。',
  device_sync_not_enabled: '当前控制台没有启用圆屏角色同步。请从启动面板核对小智目录后重启控制台。',
  device_server_unavailable: '无法读取小智配置。请确认共享服务目录仍存在且配置文件可访问。',
  device_sync_busy: '另一项圆屏角色检查或同步仍在进行，本次没有重复执行。',
  device_preview_expired: '圆屏角色同步预检已过期。请重新检查，再决定是否同步。',
  role_changed_recheck: '助手角色已在预检后发生变化。请重新检查，不能用旧预检覆盖新版本。',
  invalid_memory_marker: '小智角色配置中的记忆占位标记无效，已拒绝同步以避免破坏记忆注入。',
  device_role_sync_failed: '圆屏角色同步没有完成。请重新检查配置；没有自动重试。',
  device_sync_result_unknown: '圆屏角色同步结果未知。配置可能已经写入，请重新检查，不要重复同步。',
  invalid_body: '设置请求格式无效；没有按此请求继续操作。',
  http_400: '设置请求无效；没有按此请求继续操作。',
  http_404: '设置接口与当前页面版本不匹配。请停止旧服务并从启动面板重新启动。',
};

export function settingsFailure(error: unknown, phase: SettingsFailurePhase = 'read'): string {
  if (error instanceof ApiError) {
    const modelProblem = modelFailure(error.code);
    if (modelProblem) return modelProblem;
    const known = settingsFailureText[error.code];
    if (known) return known;
  }
  return phase === 'write'
    ? '设置结果尚未确认：配置可能已经改变。请重新读取核对，系统没有自动重试。'
    : '无法读取本机设置服务。请确认启动面板仍在运行，然后刷新页面。';
}
