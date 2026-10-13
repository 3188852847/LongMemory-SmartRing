import {describe, expect, test} from 'vitest';
import {ApiError} from '../../api';
import {settingsFailure} from './settingsFailure';

describe('设置中心安全错误说明', () => {
  test.each([
    ['model_authentication_failed', 'Key'],
    ['invalid_model_profile', '服务根地址'],
    ['voice_model_check_busy', '重复检测'],
    ['role_conflict', '重新读取'],
    ['device_sync_not_enabled', '小智目录'],
    ['device_preview_expired', '预检已过期'],
    ['role_changed_recheck', '不能用旧预检'],
    ['device_sync_result_unknown', '不要重复同步'],
  ])('%s 给出可执行提示', (code, expected) => {
    expect(settingsFailure(new ApiError(code, 409))).toContain(expected);
  });

  test('未知写入错误不回显内部码并保留结果未知语义', () => {
    const result = settingsFailure(new ApiError('private_config_detail', 500), 'write');
    expect(result).toContain('配置可能已经改变');
    expect(result).toContain('没有自动重试');
    expect(result).not.toContain('private_config_detail');
  });
});
