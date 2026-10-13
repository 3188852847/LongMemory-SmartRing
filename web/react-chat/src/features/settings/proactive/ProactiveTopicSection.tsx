import {Alert, Button, Card, Input, Select, Space, Switch, Tag} from 'antd';
import type {ProactiveTopicSeed} from '../../../api';

export interface TopicScenario {
  id: string;
  title: string;
  summary: string;
  revision: number;
}

interface Props {
  scenarios: TopicScenario[];
  scenariosLoaded: boolean;
  seeds: ProactiveTopicSeed[];
  seedsLoaded: boolean;
  scenarioId?: string;
  text: string;
  notice: string;
  createPending: boolean;
  disablePending: boolean;
  disablingId?: string;
  proactiveEnabled: boolean;
  automaticEnabled: boolean;
  topicEnabled: boolean;
  dynamicGreetingEnabled: boolean;
  onScenarioChange: (value?: string) => void;
  onTextChange: (value: string) => void;
  onCreate: () => void;
  onDisable: (seed: ProactiveTopicSeed) => void;
  onTopicEnabledChange: (value: boolean) => void;
  onDynamicGreetingEnabledChange: (value: boolean) => void;
}

/** 只展示和编辑允许公开播报的话题候选；写入及冲突处理由父层负责。 */
export function ProactiveTopicSection(props: Props) {
  return <section className="settings-section">
    <h3>记忆驱动话题素材</h3>
    <Alert type="warning" showIcon title="这里只保存你允许圆屏公开念出的短句"
      description="来源限定为当前有效且已接受的 L2 场景。仅保存素材不会自动投递；还需显式打开并保存下方开关。实际定时投递仍会经过勿扰、频率和设备状态门控。请不要填写不适合被旁人听见的信息。"/>
    <label htmlFor="topic-source">来源 L2 场景</label>
    <Select id="topic-source" aria-label="来源 L2 场景" className="wide"
      value={props.scenarioId} placeholder="选择一个已接受的生活场景"
      onChange={props.onScenarioChange}
      options={props.scenarios.map(item => ({value:item.id,label:item.title}))}/>
    <label htmlFor="topic-text">允许播出的安全话题</label>
    <Input id="topic-text" maxLength={120} showCount value={props.text}
      placeholder="例如：毕业设计汇报准备得怎么样了？"
      onChange={event => props.onTextChange(event.target.value)}/>
    <Button loading={props.createPending}
      disabled={!props.scenarioId || !props.text.trim() || props.text !== props.text.trim() || props.createPending}
      onClick={props.onCreate}>保存为话题素材</Button>
    {props.scenariosLoaded && props.scenarios.length === 0 &&
      <p className="subtle">还没有当前有效且已接受的 L2 场景；请先在“生活场景”页建立并接受场景。</p>}
    {props.notice && <p role="status">{props.notice}</p>}
    <div className="proactive-history">{props.seeds.map(seed =>
      <Card size="small" key={seed.id}
        title={<Space wrap><Tag color={seed.usable ? 'green' : 'default'}>{seed.usable ? '可用' : '不可用'}</Tag><span>{seed.prompt_text}</span></Space>}
        extra={seed.status === 'active' && <Button size="small" danger
          disabled={props.disablePending}
          loading={props.disablePending && props.disablingId === seed.id}
          onClick={() => props.onDisable(seed)}>停用</Button>}>
        <p className="subtle">来源 L2：{seed.source.title} · {seed.source.status} · 修订 {seed.revision}</p>
        <p>{seed.source.summary}</p>
        <small>素材 ID：{seed.id} · 来源 ID：{seed.scenario_id}</small>
      </Card>)}</div>
    {props.seedsLoaded && props.seeds.length === 0 && <p className="subtle">尚无话题素材。</p>}
    <div className="setting-line"><span>定时问候优先使用可用话题素材</span><Switch
      aria-label="优先使用记忆话题"
      disabled={!props.proactiveEnabled || !props.automaticEnabled}
      checked={props.topicEnabled} onChange={props.onTopicEnabledChange}/></div>
    <p className="subtle">此开关默认关闭。开启并保存后，定时点会从可用素材中优先选择最久未使用的一条；没有可用素材时仍使用上方固定问候。</p>
    <div className="setting-line"><span>让模型自然改写已批准短句</span><Switch
      aria-label="动态改写已批准话题"
      disabled={!props.topicEnabled}
      checked={props.dynamicGreetingEnabled}
      onChange={props.onDynamicGreetingEnabledChange}/></div>
    <p className="subtle">默认关闭。开启后模型只会看到已批准公开播报的短句，并须完整保留原句；3 秒内失败、输出越界或模型不可用时直接播原句。</p>
  </section>;
}
