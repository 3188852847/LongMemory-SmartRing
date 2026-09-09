import {ApiError} from './api';

export type MemoryFailurePhase = 'read' | 'write';

/** 记忆管理只展示稳定类别，不暴露 SQLite、路径或未知内部诊断。 */
const memoryFailureText: Record<string, string> = {
  session_required: '网页会话已失效，请刷新整个页面。没有自动重发记忆操作。',
  csrf_rejected: '请求校验失败，请刷新整个页面。没有自动重发记忆操作。',
  origin_rejected: '当前访问地址不符合本机安全限制。请从启动面板重新打开控制台。',
  runtime_auth_required: '本机控制台认证尚未建立。请从启动面板重新打开控制台。',
  request_rejected: '本机服务拒绝了该请求。请刷新页面后核对当前状态。',
  memory_not_configured: '启动时没有指定记忆库；页面不会自动创建数据库。',
  memory_database_missing: '配置的记忆库文件不存在。请停止服务并从启动面板核对数据库路径。',
  memory_schema_unsupported: '记忆库结构版本与当前程序不兼容。请停止服务后按迁移流程处理。',
  memory_database_unavailable: '暂时无法访问记忆库。请确认文件仍可用，并检查是否被其他程序占用。',
  memory_database_invalid: '记忆库无法安全读取。请停止写入，并先使用一致性备份核查数据库。',
  memory_busy: '记忆库正被其他操作占用。本次没有自动重试，请稍后刷新核对。',
  memory_read_only: '当前服务未开放删除权限。请在启动面板中启用所有者删除能力后重启。',
  memory_correction_disabled: '当前服务未开放纠正与事实变化权限。请在启动面板中启用后重启。',
  memory_not_found: '这条 L1 已不存在，可能已在其他页面处理。请刷新列表。',
  source_message_not_found: '这条 L0 原始记录已不存在。请刷新列表。',
  source_message_changed: '这条 L0 的关联状态已发生变化。为防止重复补记，本次操作已拒绝；请刷新后重新核对。',
  source_already_linked: '这条 L0 已经形成或支持一条 L1，不需要再次补记。请刷新详情核对。',
  promoted_source_must_be_user: '只有用户原话可以人工补成 L1；助手回答不能作为用户事实。',
  memory_changed: '这条记忆已在其他页面发生变化。为防止覆盖较新版本，本次操作已拒绝；请重新读取。',
  invalid_memory_request: '运行期记忆开关请求无效；没有应用任何设置。请刷新后重试。',
  chat_not_enabled: '共享记忆运行时尚未启动，当前不能修改运行期开关。',
  invalid_explicit_memory: '请输入以“我”或“我的”开头、关于你自己的完整事实。',
  explicit_memory_not_handled: '这条明确记忆没有完成处理。请保留原文并在聊天或记忆列表中核对。',
  http_400: '请求内容或筛选条件无效；没有按此请求修改记忆。',
  http_404: '目标记录或接口已不存在。请刷新页面核对当前版本。',
};

export function memoryFailure(error: unknown, phase: MemoryFailurePhase = 'read'): string {
  if (error instanceof ApiError) {
    const known = memoryFailureText[error.code];
    if (known) return known;
    if (error.code.startsWith('corrected_content_')) return '纠正后的事实内容无效，请填写一条完整且不同的新事实。';
    if (error.code.startsWith('changed_content_')) return '变化后的事实内容无效，请填写一条完整且不同的新事实。';
    if (error.code.startsWith('promoted_content_')) return '补记内容无效，请填写一条可独立理解的完整事实。';
    if (error.code.startsWith('effective_at_') || error.code === 'occurred_at_timezone_required') {
      return '事实生效时间无效，请重新选择包含时区的有效时间。';
    }
  }
  return phase === 'write'
    ? '操作结果尚未确认：数据可能已经改变。请刷新并重新读取，系统没有自动重试。'
    : '无法读取记忆服务。请确认控制台仍在运行，然后刷新页面。';
}
