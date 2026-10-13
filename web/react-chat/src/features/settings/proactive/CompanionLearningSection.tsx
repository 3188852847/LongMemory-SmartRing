import {Alert, Button, Card, Space, Tag} from 'antd';
import type {
  CompanionAbsenceStrategyVersion,
  CompanionAbsenceStrategyVersionList,
  CompanionRoutineCandidate,
  CompanionStrategyCandidate,
  UserInitiatedInteraction,
} from '../../../api';
import {minuteText} from './proactiveTime';

interface Props {
  strategyItems: CompanionStrategyCandidate[]; strategyLoaded:boolean; strategyFailed:boolean;
  strategyNotice:string; analyzeStrategyPending:boolean; dismissStrategyPending:boolean; dismissingStrategyId?:string;
  userItems:UserInitiatedInteraction[]; userLoaded:boolean; userFailed:boolean;
  routineItems:CompanionRoutineCandidate[]; routineLoaded:boolean; routineFailed:boolean;
  routineNotice:string; analyzeRoutinePending:boolean; dismissRoutinePending:boolean; dismissingRoutineId?:string;
  createVersionPending:boolean; creatingVersionId?:string; versionNotice:string;
  versions?:CompanionAbsenceStrategyVersionList; versionsFailed:boolean;
  switchVersionPending:boolean; switchingVersionId?:string; deactivatePending:boolean;
  onAnalyzeStrategy:()=>void; onDismissStrategy:(item:CompanionStrategyCandidate)=>void;
  onAnalyzeRoutine:()=>void; onDismissRoutine:(item:CompanionRoutineCandidate)=>void;
  onCreateVersion:(item:CompanionRoutineCandidate)=>void;
  onSwitchVersion:(version:CompanionAbsenceStrategyVersion,rollback:boolean)=>void;
  onDeactivateVersion:()=>void;
}

/** 把“观察 → 候选 → 离线验证版本”作为一条可审计链呈现，不在浏览器推断策略。 */
export function CompanionLearningSection(props:Props) {
  const switchedBefore = (id:string) => Boolean(
    props.versions?.events?.some(event => event.selected_version_id === id),
  );
  return <section className="settings-section">
    <h3>联系时段观察候选</h3>
    <Alert type="info" showIcon title="候选不会自动生效"
      description="系统只检查时间关系：至少三个不同日期、同一半小时区间内，正式问候后 30 分钟内出现用户消息，才提出一个值得试验的时刻。它不能证明你喜欢该时段，也不会写入 L3 用户画像。"/>
    <Button loading={props.analyzeStrategyPending} disabled={props.analyzeStrategyPending}
      onClick={props.onAnalyzeStrategy}>分析现有互动记录</Button>
    {props.strategyNotice && <p role="status">{props.strategyNotice}</p>}
    {props.strategyFailed && <Alert type="error" showIcon title="策略候选读取失败"/>}
    <div className="proactive-history">{props.strategyItems.map(candidate =>
      <Card size="small" key={candidate.id}
        title={<Space wrap><Tag color={candidate.status === 'candidate' ? 'gold' : 'default'}>{candidate.status === 'candidate' ? '待观察' : '已忽略'}</Tag><strong>建议试验 {minuteText(candidate.suggested_minute)}</strong><Tag>未生效</Tag></Space>}
        extra={candidate.status === 'candidate' && <Button size="small" danger
          loading={props.dismissStrategyPending && props.dismissingStrategyId === candidate.id}
          disabled={props.dismissStrategyPending}
          onClick={() => props.onDismissStrategy(candidate)}>忽略候选</Button>}>
        <p>来自 {candidate.distinct_local_dates} 个不同日期的 {candidate.evidence_count} 条时间观察。</p>
        <p className="subtle">这只是“问候后出现了消息”的时间共现，不表示因果、满意或时间偏好。</p>
        {candidate.sources.map(source => <p className="subtle" key={source.interaction_event_id}>
          {source.local_date} {minuteText(source.local_minute)} · {Math.round(source.latency_seconds / 60)} 分钟后出现用户消息 · 投递证据 {source.delivery_evidence_level}
        </p>)}
        <small>生成器：{candidate.generator_version} · 候选 ID：{candidate.id}</small>
      </Card>)}</div>
    {props.strategyLoaded && props.strategyItems.length === 0 && <p className="subtle">尚无联系时段候选。</p>}

    <h4>用户主动出现时间观察</h4>
    <p className="subtle">当前只把“距离上一条用户消息至少 4 小时，且此前 30 分钟没有主动问候”的消息记作一次观察。它是可审计的时间启发式，不等同于真实会话边界，也不会保存或展示消息正文。</p>
    {props.userFailed && <Alert type="error" showIcon title="主动出现记录读取失败"/>}
    <div className="proactive-history">{props.userItems.map(item => <Card size="small" key={item.id}>
      <p><strong>{item.local_date} {minuteText(item.local_minute)}</strong></p>
      <p className="subtle">{item.silence_gap_seconds === null ? '第一条可观察用户消息' : `此前静默约 ${Math.round(item.silence_gap_seconds / 3600 * 10) / 10} 小时`} · 近期无主动问候</p>
      <small>检测器：{item.detector_version} · 来源消息 ID：{item.source_message_id}</small>
    </Card>)}</div>
    {props.userLoaded && props.userItems.length === 0 && <p className="subtle">尚无用户主动出现时间观察。</p>}

    <h4>可能的日常交流时段</h4>
    <p className="subtle">至少三个不同日期在同一半小时区间主动出现，才会形成弱习惯候选。候选只表示重复时间规律；某天没出现不等于需要帮助，也不会自动触发问候。</p>
    <Button loading={props.analyzeRoutinePending} disabled={props.analyzeRoutinePending}
      onClick={props.onAnalyzeRoutine}>分析主动出现规律</Button>
    {props.routineNotice && <p role="status">{props.routineNotice}</p>}
    {props.routineFailed && <Alert type="error" showIcon title="主动出现时段候选读取失败"/>}
    <div className="proactive-history">{props.routineItems.map(candidate =>
      <Card size="small" key={candidate.id}
        title={<Space wrap><Tag color={candidate.status === 'candidate' ? 'gold' : 'default'}>{candidate.status === 'candidate' ? '待观察' : '已忽略'}</Tag><strong>常在 {minuteText(candidate.expected_minute)} 左右主动出现</strong><Tag>未生效</Tag></Space>}
        extra={candidate.status === 'candidate' && <Space>
          <Button size="small"
            loading={props.createVersionPending && props.creatingVersionId === candidate.id}
            disabled={props.createVersionPending}
            onClick={() => props.onCreateVersion(candidate)}>生成离线验证草案</Button>
          <Button size="small" danger
            loading={props.dismissRoutinePending && props.dismissingRoutineId === candidate.id}
            disabled={props.dismissRoutinePending}
            onClick={() => props.onDismissRoutine(candidate)}>忽略候选</Button>
        </Space>}>
        <p>来自 {candidate.distinct_local_dates} 个不同日期的 {candidate.evidence_count} 条主动出现观察。</p>
        <p className="subtle">这不是主动联系规则，也没有定义“缺席后多久问候”。</p>
        {candidate.sources.map(source => <p className="subtle" key={source.user_initiated_event_id}>
          {source.local_date} {minuteText(source.local_minute)} · {source.silence_gap_seconds === null ? '首条观察' : `此前静默约 ${Math.round(source.silence_gap_seconds / 3600 * 10) / 10} 小时`}
        </p>)}
        <small>生成器：{candidate.generator_version} · 候选 ID：{candidate.id}</small>
      </Card>)}</div>
    {props.routineLoaded && props.routineItems.length === 0 && <p className="subtle">尚无主动出现时段候选。</p>}

    {props.versionNotice && <p role="status">{props.versionNotice}</p>}
    {props.versionsFailed && <Alert type="error" showIcon title="离线验证草案读取失败"/>}
    <h4>缺席联系策略版本</h4>
    <p className="subtle">当前版本会在常见时段加上宽限后的唯一分钟参与后台检查；错过不补发，并继续遵守主动交流总开关、勿扰、频率、待回应、会话和设备门控。</p>
    <div className="proactive-history">{(props.versions?.items ?? []).map(version =>
      <Card size="small" key={version.id}
        title={<Space wrap><Tag color={version.replay_gate_passed ? 'green' : 'red'}>{version.replay_gate_passed ? '离线门控通过' : '离线门控未通过'}</Tag><strong>{minuteText(version.expected_minute)} 后宽限 {version.grace_minutes} 分钟</strong><Tag color={version.active ? 'blue' : 'default'}>{version.active ? '当前版本' : '非当前版本'}</Tag></Space>}
        extra={version.active ? <Button size="small" danger loading={props.deactivatePending}
          onClick={props.onDeactivateVersion}>停用</Button> : <Button size="small" type="primary"
          disabled={!version.replay_gate_passed || props.switchVersionPending}
          loading={props.switchVersionPending && props.switchingVersionId === version.id}
          onClick={() => props.onSwitchVersion(version, switchedBefore(version.id))}>
          {switchedBefore(version.id) ? '回滚到此版本' : '设为当前版本'}
        </Button>}>
        <p>回放匹配 {version.replay_matched_count}/{version.replay_case_count}；不安全放行 {version.replay_unsafe_allow_count}。</p>
        <p className="subtle">数据集：{version.replay_dataset_name} {version.replay_dataset_version} · 协议 {version.replay_protocol}</p>
        <small>SHA-256：{version.replay_dataset_sha256} · 来源候选：{version.source_candidate_id} 修订 {version.source_candidate_revision}</small>
      </Card>)}</div>
    {props.versions && (props.versions.items?.length ?? 0) === 0 && <p className="subtle">尚无离线验证草案。</p>}
    {(props.versions?.events?.length ?? 0) > 0 && <>
      <h4>版本切换记录</h4>
      {props.versions!.events!.map(event => <p className="subtle" key={event.id}>
        修订 {event.pointer_revision} · {event.action} · {new Date(event.created_at).toLocaleString()} · {event.previous_version_id ?? '无'} → {event.selected_version_id ?? '停用'}
      </p>)}
    </>}
  </section>;
}
