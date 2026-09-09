import {describe, expect, test} from 'vitest';
import {ApiError} from './api';
import {chatFailure} from './chatFailure';

describe('聊天入口安全错误说明', () => {
  test.each([
    ['session_required', '刷新整个页面'],
    ['csrf_rejected', '请求校验失败'],
    ['origin_rejected', '启动面板'],
    ['chat_disabled', '文字聊天尚未启用'],
    ['chat_busy', '不要重复发送'],
    ['chat_turn_limit', '40 轮'],
    ['http_404', '会话已不存在'],
  ])('%s 给出可执行提示', (code, expected) => {
    expect(chatFailure(new ApiError(code, 409))).toContain(expected);
  });

  test('未知服务端错误不会回显内部错误码', () => {
    const result = chatFailure(new ApiError('private_upstream_detail', 500), 'read');
    expect(result).toContain('无法读取本机服务状态');
    expect(result).not.toContain('private_upstream_detail');
  });

  test('写入连接中断明确要求只查询、不重发', () => {
    const result = chatFailure(new TypeError('Failed to fetch'), 'write');
    expect(result).toContain('输入可能已经保存');
    expect(result).toContain('不要重复发送');
    expect(result).not.toContain('Failed to fetch');
  });

  test('普通操作失败要求刷新核对且不自动重试', () => {
    expect(chatFailure(new Error('unknown'), 'operation')).toContain('没有自动重试');
  });
});
