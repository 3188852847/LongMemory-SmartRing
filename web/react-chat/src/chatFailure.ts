import {ApiError} from './api';

export type ChatFailurePhase = 'read' | 'operation' | 'write';

/**
 * 将控制台和聊天接口的固定错误码翻译为可执行提示。
 *
 * 这里故意不回显未知错误码、响应正文或异常字符串：聊天内容属于持久数据，
 * 写请求断线时也不能仅凭浏览器报错断言“没有保存”，更不能自动重发。
 */
const failureText: Record<string, string> = {
  session_required: '网页会话已失效，请刷新整个页面。没有自动重发任何操作。',
  csrf_rejected: '请求校验失败，请刷新整个页面。没有自动重发任何操作。',
  origin_rejected: '当前访问地址不符合本机安全限制。请从启动面板重新打开控制台。',
  runtime_auth_required: '本机控制台认证尚未建立。请从启动面板重新打开控制台。',
  bootstrap_required: '本机会话尚未建立，请刷新整个页面。',
  request_rejected: '本机服务拒绝了该请求。请刷新页面后核对当前状态。',
  chat_disabled: '文字聊天尚未启用，请通过启动面板启动控制台服务。',
  chat_capacity: '会话数量已达到上限。请先整理不再需要的网页会话；长期记忆不会随会话自动删除。',
  chat_busy: '当前会话仍在处理上一项操作。请等待完成后只查询最新状态，不要重复发送。',
  invalid_title: '聊天名称不符合要求：请填写 1 至 60 个字符。',
  invalid_chat_message: '消息格式不符合要求，请检查内容后重新输入。',
  chat_request_conflict: '同一个请求标识对应了不同内容。为避免重复写入，本次请求已拒绝。',
  chat_turn_limit: '当前网页会话已达到 40 轮上限。请新建会话；长期记忆会继续保留。',
  http_404: '这个网页会话已不存在，或不属于当前浏览器。请刷新会话列表或新建聊天。',
};

export function chatFailure(error: unknown, phase: ChatFailurePhase = 'read'): string {
  if (error instanceof ApiError && failureText[error.code]) return failureText[error.code];
  if (phase === 'write') {
    return '发送结果未知：输入可能已经保存。请只查询结果，不要重复发送。';
  }
  if (phase === 'operation') {
    return '操作结果尚未确认。请刷新页面核对最新状态；系统没有自动重试。';
  }
  return '无法读取本机服务状态。请确认启动面板仍在运行，然后刷新页面。';
}
