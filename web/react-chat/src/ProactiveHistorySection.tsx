import {Alert, Button, Space, Tag} from 'antd';
import type {ProactiveOutreachSummary} from './api';

interface Props {
  items: ProactiveOutreachSummary[];
  loading: boolean;
  failed: boolean;
  confirmingId?: string;
  confirmPending: boolean;
  onConfirm: (item: ProactiveOutreachSummary) => void;
}

/**
 * 只呈现服务端主动交流账本，不自行推断“已播放”。确认动作仍由父层执行，
 * 从而避免展示组件拥有查询缓存或写入重试策略。
 */
export function ProactiveHistorySection({
  items, loading, failed, confirmingId, confirmPending, onConfirm,
}: Props) {
  return <section className="settings-section">
    <h3>最近运行记录</h3>
    <p className="subtle">这里展示真实账本状态；排队、设备确认和播放是不同证据级别。</p>
    {failed && <Alert type="error" showIcon title="运行记录读取失败"/>}
    {loading && <p className="subtle">正在读取运行记录…</p>}
    {!loading && items.length === 0 && <p className="subtle">还没有主动交流记录。</p>}
    <div className="proactive-history">{items.map(item =>
      <article className="proactive-history-item" key={item.outreach_id}>
        <div className="setting-line">
          <Space><Tag>{item.state}</Tag><strong>{item.content}</strong></Space>
          {['queued','transport_sent','device_acknowledged'].includes(item.state) &&
            <Button size="small"
              loading={confirmPending && confirmingId === item.outreach_id}
              disabled={confirmPending}
              onClick={() => onConfirm(item)}>确认已听到</Button>}
        </div>
        <p className="subtle">{new Date(item.created_at).toLocaleString()} · 原因 {item.reason} · {item.event_count} 个事件</p>
        {item.topic_seed_id && <p className="subtle">记忆话题来源：{item.topic_seed_id} · 素材修订 {item.topic_seed_revision}</p>}
        {item.follow_up_source && <p className="subtle">长期事项来源：候选 {item.follow_up_source.candidate_id} · 修订 {item.follow_up_source.candidate_revision} · 计划 {new Date(item.follow_up_source.scheduled_for).toLocaleString('zh-CN')}</p>}
        {item.strategy_source && <p className="subtle">
          习惯策略来源：版本 {item.strategy_source.version_id} · 激活修订 {item.strategy_source.selection_revision} · 来源候选 {item.strategy_source.source_candidate_id} 修订 {item.strategy_source.source_candidate_revision}<br/>
          {item.strategy_source.evaluated_local_date} 在 {String(Math.floor((item.strategy_source.expected_minute + item.strategy_source.grace_minutes) / 60)).padStart(2,'0')}:{String((item.strategy_source.expected_minute + item.strategy_source.grace_minutes) % 60).padStart(2,'0')} 检查 · 触发器 {item.strategy_source.trigger_policy_version}
        </p>}
        {item.outcome_observation_state === 'subsequent_user_message_observed' && item.subsequent_user_message &&
          <p className="subtle">后续用户消息：已观察（{Math.round(item.subsequent_user_message.latency_seconds / 60)} 分钟后；仅表示时间先后）</p>}
        {item.outcome_observation_state === 'awaiting_subsequent_user_message' &&
          <p className="subtle">后续用户消息：尚未观察（投递证据：{item.delivery_evidence_level}）</p>}
        {item.outcome_observation_state === 'delivery_not_established' &&
          <p className="subtle">互动观察：投递未成立，不能解释为用户未回应</p>}
        {item.explicit_feedback &&
          <p className="subtle">明确反馈：用户拒绝继续使用该话题，素材已停用（用户明确陈述）</p>}
      </article>)}</div>
  </section>;
}
