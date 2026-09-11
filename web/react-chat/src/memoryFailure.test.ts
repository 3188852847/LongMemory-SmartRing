import {describe, expect, test} from 'vitest';
import {ApiError} from './api';
import {memoryFailure} from './memoryFailure';

describe('记忆管理安全错误说明', () => {
  test.each([
    ['memory_database_missing', '数据库路径'],
    ['memory_busy', '没有自动重试'],
    ['memory_read_only', '删除权限'],
    ['memory_correction_disabled', '纠正与事实变化权限'],
    ['memory_not_found', 'L1 已不存在'],
    ['source_message_changed', '重复补记'],
    ['source_already_linked', '不需要再次补记'],
    ['promoted_source_must_be_user', '用户事实'],
    ['memory_changed', '重新读取'],
    ['memory_clear_changed', '本次没有清空'],
    ['invalid_explicit_memory', '关于你自己的完整事实'],
  ])('%s 给出可行动提示', (code, expected) => {
    expect(memoryFailure(new ApiError(code, 409))).toContain(expected);
  });

  test('内容和时间校验类别不会直接展示内部码', () => {
    expect(memoryFailure(new ApiError('corrected_content_same', 400))).toContain('完整且不同');
    expect(memoryFailure(new ApiError('promoted_content_empty', 400))).toContain('补记内容无效');
    expect(memoryFailure(new ApiError('effective_at_invalid', 400))).toContain('生效时间无效');
  });

  test('未知写入错误保留结果未知语义且不泄露错误', () => {
    const result = memoryFailure(new ApiError('sqlite_private_detail', 500), 'write');
    expect(result).toContain('数据可能已经改变');
    expect(result).toContain('没有自动重试');
    expect(result).not.toContain('sqlite_private_detail');
  });
});
