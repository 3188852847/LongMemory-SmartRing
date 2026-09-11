import {Alert, Button, Checkbox, Input, InputNumber, Space, Switch} from 'antd';
import type {ProactivePolicy, ProactiveScheduleStatus} from './api';
import {minuteText, parseMinute} from './proactiveTime';

const DAYS = ['周一','周二','周三','周四','周五','周六','周日']
  .map((label, value) => ({label, value}));
const overrideResultText = (reason:string | null) => ({
  scheduled_attempt_started:'已到点并开始尝试',
  scheduled_minute_missed:'已错过设定时刻',
  configuration_changed_or_date_expired:'日期或设置已经变化',
  automatic_setting_disabled:'后台定时已经关闭',
  weekday_no_longer_allowed:'当天星期已不再允许',
  owner_cancelled:'由你主动撤销',
}[reason ?? ''] ?? reason ?? '未记录原因');

interface Props {
  draft:ProactivePolicy; dirty:boolean; notice:string;
  schedule?:ProactiveScheduleStatus; scheduleFailed:boolean;
  savePending:boolean; armPending:boolean; cancelPending:boolean;
  testText:string; testNotice:string; testPending:boolean;
  onChange:(patch:Partial<ProactivePolicy>)=>void; onSave:()=>void; onDiscard:()=>void;
  onArm:()=>void; onCancel:()=>void; onTestText:(value:string)=>void; onTest:()=>void;
}

/** 管理主动交流总许可和人工验证；所有持久化与冲突处理仍由父层协调。 */
export function ProactivePolicySection(props:Props) {
  const {draft, schedule} = props;
  const quietActive = Boolean(draft.quiet_until && new Date(draft.quiet_until).getTime() > Date.now());
  const scheduleInsideWindow = draft.allowed_start_minute < draft.allowed_end_minute
    ? draft.scheduled_minute >= draft.allowed_start_minute && draft.scheduled_minute < draft.allowed_end_minute
    : draft.scheduled_minute >= draft.allowed_start_minute || draft.scheduled_minute < draft.allowed_end_minute;
  return <>
    <section className="proactive-overview" aria-label="主动交流概览">
      <div><small>主动联系许可</small><strong className={draft.enabled ? 'is-positive' : ''}>{draft.enabled ? '已开启' : '已关闭'}</strong></div>
      <div><small>后台定时</small><strong>{draft.automatic_enabled ? minuteText(draft.scheduled_minute) : '已关闭'}</strong></div>
      <div><small>今日对话</small><strong>{schedule?.user_chatted_today ? '已聊过' : '未观察'}</strong></div>
      <div><small>上次问候</small><strong className={schedule?.awaiting_user_response ? 'is-warning' : ''}>{schedule?.awaiting_user_response ? '等待回应' : '无待回应'}</strong></div>
    </section>
    <Alert type={draft.automatic_enabled ? 'warning' : 'success'} showIcon
      title={draft.automatic_enabled ? '后台定时问候已开启' : (draft.enabled ? '主动联系许可已打开，定时问候仍关闭' : '主动交流当前关闭')}
      description="定时问候只在所选星期的指定分钟检查：当天已经聊过、设备离线或忙碌、处于勿扰或错过时刻都会跳过，之后不补发。"/>
    {schedule?.user_chatted_today && <Alert type="info" showIcon title="今天已经聊过，今天的定时问候会跳过"
      description="这是避免刚聊完又主动打扰的既定规则；修改定时时刻不会绕过它。手动验证仍可使用。"/>}
    {schedule?.awaiting_user_response && <Alert type="warning" showIcon title="上一条主动问候之后还没有收到新的用户消息"
      description="自动定时会继续停止追问；真正说出并保存一条新消息后会解除。所有者手动验证不受这一项限制。"/>}
    {props.scheduleFailed && <Alert type="error" showIcon title="暂时无法读取今天的定时状态"/>}

    <section className="settings-section">
      <h3>开发阶段：一次性定时验证</h3>
      <p className="subtle">授权后，今天下一次设定时刻可临时绕过“今天聊过”和“上一条待回应”。它不会绕过总开关、星期/时段、勿扰、频率或设备忙碌，也不会自动延续到下一天。</p>
      {schedule?.development_override ? <Alert type="warning" showIcon
        title={`已授权 ${schedule.development_override.local_date} ${minuteText(schedule.development_override.scheduled_minute)}`}
        description="到点后无论发送、拦截还是错过都会消费本次授权。"/> : <p className="subtle">当前没有待执行的一次性授权。</p>}
      {!schedule?.development_override && schedule?.latest_development_override && <p className="subtle">
        最近一次授权：{schedule.latest_development_override.status === 'cancelled' ? '已撤销' : '已消费'} · {overrideResultText(schedule.latest_development_override.consumption_reason)}
      </p>}
      <Space>
        <Button type="primary" loading={props.armPending}
          disabled={props.dirty || !draft.enabled || !draft.automatic_enabled || Boolean(schedule?.development_override) || props.armPending}
          onClick={props.onArm}>允许下一次定时验证</Button>
        <Button danger loading={props.cancelPending}
          disabled={!schedule?.development_override || props.cancelPending}
          onClick={props.onCancel}>撤销一次性授权</Button>
      </Space>
    </section>

    <section className="settings-section proactive-policy-section">
      <h3>联系许可与时间边界</h3>
      <p className="subtle">这些是所有自动问候都必须通过的总边界；修改后需要显式保存。</p>
      <div className="setting-line"><span>允许主动联系</span><Switch aria-label="允许主动联系" checked={draft.enabled}
        onChange={enabled => props.onChange({enabled, ...(!enabled ? {automatic_enabled:false, topic_enabled:false} : {})})}/></div>
      <div className="setting-line"><span>后台定时问候</span><Switch aria-label="后台定时问候" disabled={!draft.enabled} checked={draft.automatic_enabled}
        onChange={automatic_enabled => props.onChange({automatic_enabled, ...(!automatic_enabled ? {topic_enabled:false} : {})})}/></div>
      <label>允许星期</label>
      <Checkbox.Group aria-label="允许星期" options={DAYS} value={draft.allowed_weekdays}
        onChange={values => props.onChange({allowed_weekdays:values.map(Number).sort()})}/>
      <div className="proactive-fields">
        <div><label htmlFor="proactive-start">开始时间</label><Input id="proactive-start" type="time" value={minuteText(draft.allowed_start_minute)} onChange={event => props.onChange({allowed_start_minute:parseMinute(event.target.value)})}/></div>
        <div><label htmlFor="proactive-end">结束时间</label><Input id="proactive-end" type="time" value={minuteText(draft.allowed_end_minute)} onChange={event => props.onChange({allowed_end_minute:parseMinute(event.target.value)})}/></div>
        <div><label htmlFor="proactive-daily">每天最多次数</label><InputNumber id="proactive-daily" min={1} max={20} value={draft.daily_limit} onChange={value => value && props.onChange({daily_limit:value})}/></div>
        <div><label htmlFor="proactive-gap">最短间隔（小时）</label><InputNumber id="proactive-gap" min={0} max={168} value={draft.minimum_interval_seconds / 3600} onChange={value => value !== null && props.onChange({minimum_interval_seconds:Math.round(value * 3600)})}/></div>
        <div><label htmlFor="proactive-schedule">定时问候时刻</label><Input id="proactive-schedule" type="time" value={minuteText(draft.scheduled_minute)} onChange={event => props.onChange({scheduled_minute:parseMinute(event.target.value)})}/></div>
      </div>
      <label htmlFor="proactive-greeting">固定问候内容</label>
      <Input id="proactive-greeting" maxLength={80} showCount value={draft.greeting_text} onChange={event => props.onChange({greeting_text:event.target.value})}/>
      {draft.automatic_enabled && !scheduleInsideWindow && <Alert type="error" showIcon title="定时问候时刻必须位于允许时段内"/>}
      <p className="subtle">时区：UTC{draft.utc_offset_minutes >= 0 ? '+' : ''}{draft.utc_offset_minutes / 60}（第一版固定偏移）；消息超过 {draft.maximum_lifetime_seconds / 60} 分钟就不再投递。</p>
      <div className="setting-line"><span>{quietActive ? `临时勿扰至 ${new Date(draft.quiet_until!).toLocaleString()}` : '临时勿扰未开启'}</span><Space>
        <Button onClick={() => props.onChange({quiet_until:new Date(Date.now() + 60 * 60 * 1000).toISOString()})}>勿扰 1 小时</Button>
        <Button disabled={!draft.quiet_until} onClick={() => props.onChange({quiet_until:null})}>解除勿扰</Button>
      </Space></div>
      <Space><Button type="primary" loading={props.savePending}
        disabled={!props.dirty || draft.allowed_weekdays.length === 0 || draft.allowed_start_minute === draft.allowed_end_minute || (draft.automatic_enabled && !scheduleInsideWindow) || !draft.greeting_text.trim() || draft.greeting_text !== draft.greeting_text.trim()}
        onClick={props.onSave}>保存主动交流设置</Button>
        <Button disabled={!props.dirty || props.savePending} onClick={props.onDiscard}>放弃修改</Button></Space>
      {props.notice && <p role="status">{props.notice}</p>}
    </section>

    <section className="settings-section">
      <h3>手动验证圆屏问候</h3>
      <p className="subtle">每次点击只尝试一次。它由你明确触发，因此不受“等待用户回应”限制；仍遵守总开关、时间段、勿扰、频率和设备忙碌限制，失败不会自动重试。</p>
      <Input aria-label="测试问候内容" maxLength={80} showCount value={props.testText} onChange={event => props.onTestText(event.target.value)}/>
      <Button loading={props.testPending}
        disabled={!draft.enabled || props.dirty || props.testPending || !props.testText.trim() || props.testText !== props.testText.trim()}
        onClick={props.onTest}>发送一次测试问候</Button>
      {!draft.enabled && <p className="subtle">请先打开并保存“允许主动联系”，再进行测试。</p>}
      {props.dirty && <p className="subtle">当前设置尚未保存，请保存或放弃修改后再测试。</p>}
      {props.testNotice && <p role="status">{props.testNotice}</p>}
    </section>
  </>;
}
