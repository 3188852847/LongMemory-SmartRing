import {useId} from 'react';
import {Alert, Button, Card, Empty, Space, Tag} from 'antd';
import type {DiagnosticOutcome, DiagnosticSnapshot} from './types';
import './observability.css';

const outcomes: Record<DiagnosticOutcome, string> = {
  processing: '处理中', succeeded: '读取响应已生成', accepted: '请求已接收，完成另行核对',
  failed: '请求失败', unknown: '执行结果未知，请重新读取状态',
};
const stages: Record<string, string> = {
  request: 'HTTP 边界', storage: '记忆存储', extraction: '记忆提取',
  retrieval: '记忆召回', context: '上下文构建', model: '回答模型',
};
const operations: Record<string, string> = {
  chat: '文字聊天', device: '设备请求', memory: '记忆管理',
  memory_runtime: '圆屏记忆接口', console: '控制台请求', diagnostics: '故障观察',
};
const voiceEvents: Record<string, string> = {
  asr_entered: '识别包装器已进入', asr_handoff: '识别结果已交给聊天入口', asr_failed: '识别包装器失败或取消',
  chat_entered: '聊天入口已进入', chat_returned: '聊天方法已返回', chat_failed: '聊天方法失败',
  memory_requested: '记忆已请求', memory_response: '记忆响应已读取', memory_failed: '记忆失败',
  model_requested: '模型已请求', model_output: '模型已有输出', model_returned: '模型迭代已返回', model_failed: '模型失败',
  tts_requested: '合成方法已调用', tts_response: '合成 HTTP 响应头已收到', tts_audio_ready: '编码音频已产生',
  tts_returned: '合成方法已返回', tts_failed: '合成失败', tts_cancelled: '合成取消或已过期', tts_fallback: '已回退兼容合成',
  send_returned: '服务端首次音频发送已返回', cancelled: '已取消', superseded: '已有新轮次',
  asr_timeout: '识别超时', memory_timeout: '记忆请求超时', model_timeout: '模型超时', tts_timeout: '合成请求超时',
  tts_service_entered: '合成服务已进入生成', tts_service_returned: '合成服务生成方法已返回',
  tts_service_written: '合成服务已写出响应', tts_service_failed: '合成服务生成失败',
  tts_service_disconnected: '合成服务观察到连接断开', tts_service_busy: '合成服务忙碌拒绝',
};
const bytes = (value: number) => `${(value / 1024 / 1024).toFixed(2)} MiB`;

export interface DiagnosticsPanelProps {
  snapshot?: DiagnosticSnapshot;
  loading?: boolean;
  error?: boolean;
  onRefresh: () => void;
}

/** 主页面负责数据读取；此组件不启动服务、不轮询、不触发业务重试。 */
export function DiagnosticsPanel({snapshot, loading = false, error = false, onRefresh}: DiagnosticsPanelProps) {
  const headingId = useId();
  return <section className="observability-panel" aria-labelledby={headingId}>
    <Card title={<span id={headingId}>安全故障摘要</span>} extra={
      <Button aria-label="刷新摘要" onClick={onRefresh} loading={loading}>刷新摘要</Button>
    }>
      <p>摘要仅包含当前 API 进程观测到的请求。请求返回不代表后台任务完成，设备播放仍未确认。</p>
      {error && <Alert role="alert" type="error" showIcon title="摘要暂不可读取"
        description="请刷新摘要核对当前状态。此处不会重新执行失败的业务操作。"/>}
      {loading && <p role="status">正在读取安全摘要…</p>}
      {snapshot?.persistence === 'unavailable' && <Alert role="status" type="warning" showIcon
        title="诊断文件暂不可写入" description="当前内存摘要仍可查看；文件记录可能不完整。"/>}
      {!loading && !error && (!snapshot || snapshot.requests.length === 0) &&
        <Empty description="当前进程尚无请求记录；重启前记录未加载"/>}
      {snapshot && snapshot.requests.length > 0 && <ol>
        {snapshot.requests.slice(0, 20).map(row => <li key={row.request_id}>
          <Space wrap>
            <strong>{operations[row.operation] ?? '控制台请求'}</strong>
            <Tag color={row.outcome === 'failed' ? 'red' : row.outcome === 'unknown' ? 'gold' : 'default'}>
              {outcomes[row.outcome] ?? '状态未确认'}
            </Tag>
            <span>{stages[row.stage] ?? '阶段未确认'} · {row.duration_ms} ms</span>
          </Space>
          <p>结果码：{row.code} · 请求标识：<code>{row.request_id}</code></p>
          {row.voice_round_id && <p>关联语音轮次：<code>{row.voice_round_id}</code></p>}
          <p><time dateTime={row.time}>{new Date(row.time).toLocaleString('zh-CN')}</time></p>
          <details>
            <summary>查看已观测阶段</summary>
            {row.stages.length === 0 ? <p>尚未观测到记忆阶段；HTTP 耗时不能用于推断模型耗时。</p> : <ul>
              {row.stages.map((phase, index) => <li key={index}>
                {stages[phase.stage] ?? '阶段未确认'} · {phase.event} · 距请求入口 {phase.at_ms} ms
              </li>)}
            </ul>}
          </details>
        </li>)}
      </ol>}
      <details>
        <summary>语音轮次与缺失阶段</summary>
        <p>轮次标识独立于单次 HTTP 请求。这里只显示已收到的包装器事件；观测可能丢失，设备播放未确认。</p>
        {!snapshot?.voice?.rounds.length && <p>当前进程尚未收到语音事件；请核对更新后的语音进程是否已接入。</p>}
        {snapshot?.voice?.rounds.slice(0, 20).map(round => <article key={round.round_id}>
          <p>语音轮次：<code>{round.round_id}</code> · {
            round.state === 'cancelled' ? '已取消或已有新轮次' : round.state === 'failure_observed' ? '观察到失败' : '完成状态未确认'}</p>
          <p>关联缺失：{round.missing.length ? round.missing.map(name => voiceEvents[name] ?? '未知阶段').join('、') : '所列包装器事件均已收到；不代表播放完成'}</p>
          {round.sequence_gaps.length > 0 && <p>事件序号缺失：{round.sequence_gaps.join('、')}，可能尚在投递或已丢失。</p>}
          {!!round.source_gaps?.some(gap => gap.source === 'cosyvoice') && <p>合成服务事件存在缺号，请核对后再判断完成状态。</p>}
          {round.truncated && <p>本轮达到摘要条目上限，后续事件未保留。</p>}
          <ul>{round.events.map(event => <li key={`${event.source ?? 'xiaozhi'}-${event.http_request_id ?? ''}-${event.sequence}`}>
            {event.source === 'cosyvoice' ? '合成服务进程' : '语音包装器进程'} · {voiceEvents[event.event] ?? '未识别的观测事件'}
            {event.http_request_id && <> · HTTP 标识：<code>{event.http_request_id}</code></>}
          </li>)}</ul>
        </article>)}
        <p>各进程事件按自身序号显示，不推算跨进程耗时。生成方法返回、写出响应和设备播放分别核对；播放始终未确认。原有首句时序由设备页独立展示。</p>
      </details>
      <details>
        <summary>历次日志容量与保留预算</summary>
        {snapshot?.log_retention ? <>
          {snapshot.log_retention.state === 'unconfigured' ? <p role="status">当前服务尚未提供日志容量统计。</p> :
            <p>固定目录已统计 {bytes(snapshot.log_retention.total_bytes)}；项目管理范围 {bytes(snapshot.log_retention.managed_bytes)}，
              预算 {bytes(snapshot.log_retention.budget_bytes)}。厂家日志 {bytes(snapshot.log_retention.vendor_bytes)} 单独核对归属。</p>}
          <p>仅作只读预演，最短保留 {snapshot.log_retention.min_age_days} 天。活动或归属未确认的日志受保护，未执行删除。</p>
          {!snapshot.log_retention.complete && <p role="status">统计范围不完整，无法据此生成清理候选；请核对链接、访问权限或扫描上限。</p>}
          {!!snapshot.log_retention.unresolved_bytes && <p role="status">仍有 {bytes(snapshot.log_retention.unresolved_bytes)} 超出预算且受保护；需要先确认日志写入者和证据保留要求。</p>}
        </> : <p>当前服务尚未提供累计保留元数据。</p>}
      </details>
    </Card>
  </section>;
}
