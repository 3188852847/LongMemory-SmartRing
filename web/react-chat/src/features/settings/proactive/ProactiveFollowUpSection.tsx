import {Alert, Button, Card, Input, Select, Space, Tag} from 'antd';
import type {FollowUpCandidate} from '../../../api';

interface MemorySource {id:string;content:string;state:string}
interface Props {
  sources: MemorySource[];
  items: FollowUpCandidate[];
  loaded: boolean;
  failed: boolean;
  sourceId?: string;
  text: string;
  localTime: string;
  notice: string;
  createPending: boolean;
  cancelPending: boolean;
  armPending: boolean;
  cancellingId?: string;
  armingId?: string;
  proactiveEnabled: boolean;
  policyDirty: boolean;
  onSourceChange: (value?: string) => void;
  onTextChange: (value: string) => void;
  onLocalTimeChange: (value: string) => void;
  onCreate: () => void;
  onCancel: (item: FollowUpCandidate) => void;
  onArm: (item: FollowUpCandidate) => void;
}

/** 呈现可追溯的一次性跟进候选；服务端修订和投递护栏仍由父层执行。 */
export function ProactiveFollowUpSection(props: Props) {
  const time = new Date(props.localTime).getTime();
  const invalidTime = !props.localTime || Number.isNaN(time) || time <= Date.now();
  return <section className="settings-section">
    <h3>长期事项跟进候选</h3>
    <Alert type="info" showIcon title="这里只建立可追溯候选，不会自动联系圆屏"
      description="选择一条当前 L1 作为依据，并明确写下未来适合追问的短句。候选需要另行启用才会成为一次性未来任务；到点仍会经过全部主动交流护栏。"/>
    <label htmlFor="follow-up-source">依据的 L1 原子记忆</label>
    <Select id="follow-up-source" aria-label="跟进来源 L1" className="wide"
      value={props.sourceId} placeholder="选择一条明确计划或待办"
      onChange={props.onSourceChange}
      options={props.sources.map(item => ({value:item.id,label:item.content}))}/>
    <label htmlFor="follow-up-text">以后适合问的一句话</label>
    <Input id="follow-up-text" maxLength={160} showCount value={props.text}
      placeholder="例如：毕业设计汇报准备得怎么样了？"
      onChange={event => props.onTextChange(event.target.value)}/>
    <label htmlFor="follow-up-time">计划跟进时间</label>
    <Input id="follow-up-time" type="datetime-local" value={props.localTime}
      onChange={event => props.onLocalTimeChange(event.target.value)}/>
    <Button loading={props.createPending}
      disabled={!props.sourceId || !props.text.trim() || props.text !== props.text.trim() || invalidTime || props.createPending}
      onClick={props.onCreate}>建立跟进候选</Button>
    {props.notice && <p role="status">{props.notice}</p>}
    {props.failed && <Alert type="error" showIcon title="跟进候选读取失败"/>}
    <div className="proactive-history">{props.items.map(item =>
      <Card size="small" key={item.id}
        title={<Space wrap>
          <Tag color={item.activation ? 'blue' : item.ready_for_activation ? 'gold' : 'default'}>
            {item.status === 'cancelled' ? '已取消' : item.activation ? '已启用' : item.due ? '已到时间' : '候选'}
          </Tag>
          <strong>{item.prompt_text}</strong>{!item.activation && <Tag>未启用</Tag>}
        </Space>}
        extra={item.status === 'candidate' && <Space>
          {item.ready_for_activation && <Button size="small" type="primary"
            loading={props.armPending && props.armingId === item.id}
            disabled={!props.proactiveEnabled || props.policyDirty || props.armPending || props.cancelPending}
            onClick={() => props.onArm(item)}>启用一次跟进</Button>}
          <Button size="small" danger
            loading={props.cancelPending && props.cancellingId === item.id}
            disabled={props.cancelPending || props.armPending || Boolean(item.activation && item.activation.state !== 'candidate')}
            onClick={() => props.onCancel(item)}>{item.activation ? '取消未执行跟进' : '取消候选'}</Button>
        </Space>}>
        <p>计划时间：{new Date(item.follow_up_at).toLocaleString('zh-CN')}</p>
        <p className="subtle">形成方式：{item.creation_kind === 'explicit_conversation_request' ? '来自明确对话请求' : '控制台手动创建'}</p>
        <p className="subtle">依据 L1：{item.source.content}</p>
        {item.activation && <p className="subtle">一次性账本：{item.activation.state} · 过期时间 {new Date(item.activation.expires_at).toLocaleString('zh-CN')}</p>}
        {!item.ready_for_activation && !item.activation && item.status === 'candidate' &&
          <p className="subtle">当前不可启用：{item.blocked_reason === 'source_changed' ? '来源已变化或退役' : item.blocked_reason === 'time_reached' ? '计划时间已经到达' : item.blocked_reason}</p>}
        {!props.proactiveEnabled && item.ready_for_activation && <p className="subtle">启用前需先打开并保存上方主动交流总许可。</p>}
        <small>候选 ID：{item.id} · 来源 ID：{item.source_memory_id} · 修订 {item.revision}</small>
      </Card>)}</div>
    {props.loaded && props.items.length === 0 && <p className="subtle">尚无跟进候选。</p>}
  </section>;
}
