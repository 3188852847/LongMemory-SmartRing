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
      <p>语音识别、合成与设备播放尚未纳入此摘要。现有圆屏首句时序仍由设备页独立展示。</p>
    </Card>
  </section>;
}
