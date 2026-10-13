import {describe, expect, test} from 'vitest';
import {ApiError} from '../../api';
import {derivedMemoryFailure} from './derivedMemoryFailure';

describe('L2/L3 安全错误说明', () => {
  test.each([
    ['scenario_requires_distinct_l1_sources', '两条不同'],
    ['scenario_proposal_no_coherent_group', '没有找到'],
    ['scenario_review_revision_mismatch', '重新打开'],
    ['persona_declared_requires_user_l0', '用户 L0 原话'],
    ['persona_inference_evidence_threshold_not_met', '3 条用户原话'],
    ['persona_replacement_target_not_active', '旧画像已经失效'],
    ['persona_review_conflict', '不能用旧页面'],
  ])('%s 给出可执行提示', (code, expected) => {
    expect(derivedMemoryFailure(new ApiError(code, 409), 'write')).toContain(expected);
  });

  test('未知模型预览错误不回显内部码且明确没有落库', () => {
    const result = derivedMemoryFailure(new ApiError('private_model_detail', 500), 'preview');
    expect(result).toContain('没有写入候选');
    expect(result).not.toContain('private_model_detail');
  });

  test('数据库错误继续复用记忆页安全说明', () => {
    expect(derivedMemoryFailure(new ApiError('memory_busy', 503), 'read')).toContain('没有自动重试');
  });
});
