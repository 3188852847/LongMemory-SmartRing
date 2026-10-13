import {ApiError} from '../../api';
import {modelFailure} from '../settings/modelHealth';

export type ExperimentFailurePhase = 'read' | 'prepare' | 'start' | 'stop' | 'review';

const experimentFailureText: Record<string, string> = {
  session_required: '网页会话已失效，请刷新整个页面。没有自动重发实验操作。',
  csrf_rejected: '请求校验失败，请刷新整个页面。没有自动重发实验操作。',
  origin_rejected: '当前访问地址不符合本机安全限制。请从启动面板重新打开控制台。',
  experiment_not_found: '这份实验档案已不存在，请刷新档案列表。',
  experiment_unreadable: '实验档案不完整或格式不受支持；没有把它计为通过。',
  unsupported_report: '该报告版本暂不支持逐题阅读或人工复核。',
  duplicate_report_rows: '报告中存在重复题目记录，已拒绝按不确定数据展示。',
  question_not_found: '所选题目不在当前冻结报告中，请刷新题目列表。',
  experiment_runs_disabled: '当前服务只允许查看档案。请从启动面板显式启用实验运行。',
  experiment_busy: '另一个实验操作正在占用运行账本，本次没有重复执行。',
  dev_retrieval_required: '只能使用已完成的开发集冻结检索档案，请重新选择来源。',
  source_not_unique: '冻结检索来源不唯一，无法建立可复现报价。',
  experiment_too_large: '实验档案超过当前安全读取上限，已拒绝运行或展示。',
  report_changed: '冻结报告已在预检后变化。请重新预检，不能沿用旧报价或复核。',
  request_limit_exceeded: '本次实验请求预算超过允许上限，请降低题量或上下文预算。',
  invalid_job_request: '实验启动参数无效，本次没有启动任务。',
  job_input_or_storage_invalid: '实验输入或运行账本无效，本次操作没有按原请求继续。',
  model_not_configured: '真实回答模型尚未配置。请先在设置中心完成模型配置并重启。',
  confirmation_required: '实验启动需要重新核对并明确确认模型、预算和网络风险。',
  network_confirmation_required: '联网实验必须明确确认网络与凭据传输风险。',
  quote_expired: '实验预检报价已过期，请重新预检预算后再启动。',
  job_limit: '已有实验任务正在运行或等待结束，不能同时启动另一项。',
  job_request_conflict: '同一启动请求对应了不同参数。为避免重复调用模型，本次已拒绝。',
  job_not_owned_or_finished: '该任务不属于当前会话或已经结束，不能再次停止。',
  invalid_review: '人工复核内容无效；请核对结论、理由和署名。',
  answers_required: '该档案没有回答结果，不能保存回答质量复核。',
  review_limit: '这份档案的人工复核版本已达到上限。',
  request_conflict: '同一复核请求对应了不同内容。为避免重复写入，本次已拒绝。',
  review_changed: '同一署名的复核已在其他页面变化。请刷新后继续。',
};

/** 可用于接口异常，也可安全解释任务账本中的固定 error code。 */
export function experimentCodeText(code: unknown): string | undefined {
  if (typeof code !== 'string') return undefined;
  return modelFailure(code) ?? experimentFailureText[code];
}

export function experimentFailure(error: unknown, phase: ExperimentFailurePhase = 'read'): string {
  if (error instanceof ApiError) {
    const known = experimentCodeText(error.code);
    if (known) return known;
  }
  if (phase === 'prepare') return '预检没有完成，实验没有启动，也没有调用回答模型。';
  if (phase === 'start') return '启动结果尚未确认。请只刷新任务台账核对，不要创建新的启动请求。';
  if (phase === 'stop') return '停止请求的结果尚未确认。请刷新任务状态，系统没有自动重复停止。';
  if (phase === 'review') return '复核结果尚未确认，可能已经另存。请刷新档案核对，不要重复保存。';
  return '无法读取实验档案或任务状态。请确认控制台仍在运行，然后刷新页面。';
}
