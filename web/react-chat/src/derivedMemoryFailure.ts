import {ApiError} from './api';
import {memoryFailure} from './memoryFailure';

export type DerivedMemoryFailurePhase = 'read' | 'preview' | 'write';

/** L2/L3 页面把研究内部约束翻译成所有者可以采取的下一步。 */
const derivedFailureText: Record<string, string> = {
  scenario_management_disabled: '当前进程未开放 L2 管理权限。只读浏览仍可用；需要编辑时请从日常启动面板重启。',
  scenario_model_preview_unavailable: 'L2 草稿模型当前不可用。仍可手工创建候选，或到模型设置中检查连接。',
  scenario_not_found: '这条 L2 场景已不存在。请关闭详情并刷新列表。',
  scenario_requires_distinct_l1_sources: 'L2 至少需要两条不同的 L1 来源，请重新选择。',
  scenario_requires_distinct_user_l0_sources: '所选 L1 没有提供足够的不同用户原话，不能形成可审计的 L2 草稿。',
  scenario_source_l1_missing: '所选 L1 已不存在，请刷新来源列表后重新选择。',
  scenario_source_l1_retired: '所选 L1 已退役，不能再用于新建 L2；请改选当前有效来源。',
  scenario_source_subject_mismatch: '所选来源不属于同一用户，已拒绝合并。',
  scenario_valid_time_invalid: 'L2 的现实有效时间无效，请重新选择开始和结束时间。',
  scenario_proposal_no_coherent_group: '模型没有找到至少两条共同支持同一生活场景的记忆；本次没有生成草稿。',
  scenario_proposal_generation_failed: 'L2 模型草稿生成失败；没有写入数据库，也没有自动重试。',
  scenario_review_revision_mismatch: '这条 L2 已在其他页面变化。请重新打开详情后再复核。',
  scenario_review_conflict: '这条 L2 已经完成复核，不能用旧页面重复决定。请刷新详情。',
  scenario_lifecycle_conflict: '这条 L2 的状态已经变化，不能重复结束。请刷新详情。',
  persona_management_disabled: '当前进程未开放 L3 管理权限。只读浏览仍可用；需要编辑时请从日常启动面板重启。',
  persona_model_preview_unavailable: 'L3 整理模型当前不可用。仍可手工创建候选，或到模型设置中检查连接。',
  persona_not_found: '这条 L3 画像已不存在。请关闭详情并刷新列表。',
  persona_sources_invalid: 'L3 来源无效或重复，请重新选择至少一条有效 L1/L2。',
  persona_source_missing_or_inactive: '所选 L1/L2 已不存在或已失效，请刷新来源后重新选择。',
  persona_source_subject_mismatch: '所选来源不属于同一用户，已拒绝合并。',
  persona_declared_requires_user_l0: '“用户声明”必须能追溯到至少一条用户 L0 原话。',
  persona_inference_evidence_threshold_not_met: '系统推断证据不足：至少需要 2 个来源、3 条用户原话和 2 个观察日。',
  persona_valid_time_invalid: 'L3 的现实有效时间无效，请重新选择开始和结束时间。',
  persona_replacement_target_not_active: '准备取代的旧画像已经失效。请刷新画像后重新创建更新候选。',
  persona_replacement_kind_mismatch: '新旧画像类型不同，不能建立取代关系。',
  persona_replacement_subject_mismatch: '新旧画像不属于同一用户，已拒绝取代。',
  persona_proposal_no_supported_claim: '模型没有找到证据充分的画像认识；本次没有生成候选。',
  persona_proposal_generation_failed: 'L3 模型建议生成失败；没有写入数据库，也没有自动重试。',
  persona_consolidation_generation_failed: 'L3 整理建议生成失败；没有写入数据库，也没有自动重试。',
  persona_review_revision_mismatch: '这条 L3 已在其他页面变化。请重新打开详情后再复核。',
  persona_review_conflict: '这条 L3 已经完成复核，不能用旧页面重复决定。请刷新详情。',
  persona_replacement_conflict: '拟取代画像的状态已变化。没有覆盖任何较新画像，请刷新后重新核对。',
};

export function derivedMemoryFailure(error: unknown, phase: DerivedMemoryFailurePhase = 'read'): string {
  if (error instanceof ApiError && derivedFailureText[error.code]) return derivedFailureText[error.code];
  if (phase === 'preview') return '模型预览没有完成：没有写入候选，也没有自动重试。请检查模型状态后再决定是否重试。';
  return memoryFailure(error, phase === 'write' ? 'write' : 'read');
}
