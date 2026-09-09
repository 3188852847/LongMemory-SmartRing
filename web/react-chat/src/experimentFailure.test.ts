import {describe, expect, test} from 'vitest';
import {ApiError} from './api';
import {experimentCodeText, experimentFailure} from './experimentFailure';

describe('实验中心安全错误说明', () => {
  test.each([
    ['experiment_runs_disabled', '查看档案'],
    ['dev_retrieval_required', '开发集冻结检索'],
    ['quote_expired', '重新预检'],
    ['model_not_configured', '设置中心'],
    ['job_request_conflict', '避免重复调用模型'],
    ['review_changed', '其他页面变化'],
    ['model_authentication_failed', 'Key'],
  ])('%s 给出可执行提示', (code, expected) => {
    expect(experimentFailure(new ApiError(code, 409), 'start')).toContain(expected);
  });

  test('未知启动错误要求只查台账且不泄露内部码', () => {
    const result = experimentFailure(new ApiError('private_runner_detail', 500), 'start');
    expect(result).toContain('只刷新任务台账');
    expect(result).not.toContain('private_runner_detail');
  });

  test('任务账本未知状态码不直接显示', () => {
    expect(experimentCodeText('model_request_timeout')).toContain('超时');
    expect(experimentCodeText('private_job_trace')).toBeUndefined();
  });
});
