import {Alert, Button, Checkbox, Collapse, Input, InputNumber, Space, Switch} from 'antd';
import type {ProactivePolicy, ProactiveScheduleStatus} from '../../../api';
import {minuteText, parseMinute} from './proactiveTime';

const DAYS = ['周一','周二','周三','周四','周五','周六','周日']
  .map((label, value) => ({label, value}));
const overrideResultText = (reason:string | null) => ({
  scheduled_attempt_started:'已到点并开始尝试', scheduled_minute_missed:'已错过设定时刻',
  configuration_changed_or_date_expired:'日期或设置已经变化', automatic_setting_disabled:'周期问候已经关闭',
  interval_mode_does_not_use_override:'已切换为间隔问候', weekday_no_longer_allowed:'当天星期已不再允许',
  owner_cancelled:'由你主动撤销',
}[reason ?? ''] ?? reason ?? '未记录原因');

export function proactiveFrequencyText(seconds:number) {
  if (seconds === 86400) return '每天一次';
  if (seconds % 3600 === 0) return `每 ${seconds / 3600} 小时一次`;
  return `每 ${seconds / 60} 分钟一次`;
}

interface Props {
  draft:ProactivePolicy; dirty:boolean; notice:string;
  schedule?:ProactiveScheduleStatus; scheduleFailed:boolean;
  savePending:boolean; armPending:boolean; cancelPending:boolean;
  testText:string; testNotice:string; testPending:boolean;
  onChange:(patch:Partial<ProactivePolicy>)=>void; onSave:()=>void; onDiscard:()=>void;
  onArm:()=>void; onCancel:()=>void; onTestText:(value:string)=>void; onTest:()=>void;
}

/** 常用开关与频率直接呈现；时间边界和诊断动作按需展开。 */
export function ProactivePolicySection(props:Props) {
  const {draft, schedule} = props;
  const intervalMinutes = draft.automatic_interval_seconds / 60;
  const dailyMode = draft.automatic_interval_seconds === 86400;
  const quietActive = Boolean(draft.quiet_until && new Date(draft.quiet_until).getTime() > Date.now());
  const scheduleInsideWindow = draft.allowed_start_minute < draft.allowed_end_minute
    ? draft.scheduled_minute >= draft.allowed_start_minute && draft.scheduled_minute < draft.allowed_end_minute
    : draft.scheduled_minute >= draft.allowed_start_minute || draft.scheduled_minute < draft.allowed_end_minute;
  const setFrequency = (minutes:number | null) => {
    if (minutes === null || minutes < 1 || minutes > 1440) return;
    const rounded = Math.round(minutes);
    const seconds = rounded * 60;
    // 后台轮询可能晚于整分钟时间槽，防抖少留 1 分钟可避免连续时间槽被误拦。
    // 是否到达新周期仍由后端时间槽和幂等键决定。
    props.onChange({automatic_interval_seconds:seconds, minimum_interval_seconds:Math.max(0, seconds - 60),
      daily_limit:Math.ceil(1440 / rounded)});
  };

  const advanced = [
    {key:'boundaries', label:'允许时间与勿扰', children:<Space orientation="vertical" style={{width:'100%'}}>
      <label>允许星期</label>
      <Checkbox.Group aria-label="允许星期" options={DAYS} value={draft.allowed_weekdays}
        onChange={values=>props.onChange({allowed_weekdays:values.map(Number).sort()})}/>
      <div className="proactive-fields">
        <div><label htmlFor="proactive-start">开始时间</label><Input id="proactive-start" type="time" value={minuteText(draft.allowed_start_minute)} onChange={event=>props.onChange({allowed_start_minute:parseMinute(event.target.value)})}/></div>
        <div><label htmlFor="proactive-end">结束时间</label><Input id="proactive-end" type="time" value={minuteText(draft.allowed_end_minute)} onChange={event=>props.onChange({allowed_end_minute:parseMinute(event.target.value)})}/></div>
        {dailyMode&&<div><label htmlFor="proactive-schedule">每日问候时刻</label><Input id="proactive-schedule" type="time" value={minuteText(draft.scheduled_minute)} onChange={event=>props.onChange({scheduled_minute:parseMinute(event.target.value)})}/></div>}
      </div>
      <p className="subtle">{dailyMode?'每天在所选时刻检查一次。':'短周期会在保存并开启后，从下一个允许分钟自动开始，不需要设置锚点。'}只在允许星期与时段内运行。当前每日上限随频率自动设为 {draft.daily_limit} 次。</p>
      <div className="setting-line"><span>{quietActive ? `临时勿扰至 ${new Date(draft.quiet_until!).toLocaleString()}` : '临时勿扰未开启'}</span><Space>
        <Button onClick={()=>props.onChange({quiet_until:new Date(Date.now()+60*60*1000).toISOString()})}>勿扰 1 小时</Button>
        <Button disabled={!draft.quiet_until} onClick={()=>props.onChange({quiet_until:null})}>解除勿扰</Button>
      </Space></div>
      <p className="subtle">时区：UTC{draft.utc_offset_minutes>=0?'+':''}{draft.utc_offset_minutes/60}；单次消息超过 {draft.maximum_lifetime_seconds/60} 分钟不再补发。</p>
    </Space>},
    {key:'diagnostics', label:'测试与诊断', children:<Space orientation="vertical" style={{width:'100%'}}>
      {dailyMode && <section className="settings-section">
        <h3>一次性定时验证</h3>
        <p className="subtle">仅为“每天一次”模式临时绕过今天已聊过和上一条待回应；其他护栏保持。</p>
        {schedule?.development_override ? <Alert type="warning" showIcon title={`已授权 ${schedule.development_override.local_date} ${minuteText(schedule.development_override.scheduled_minute)}`}/>:<p className="subtle">当前没有待执行的一次性授权。</p>}
        {!schedule?.development_override&&schedule?.latest_development_override&&<p className="subtle">最近一次授权：{schedule.latest_development_override.status==='cancelled'?'已撤销':'已消费'} · {overrideResultText(schedule.latest_development_override.consumption_reason)}</p>}
        <Space><Button type="primary" loading={props.armPending} disabled={props.dirty||!draft.enabled||!draft.automatic_enabled||Boolean(schedule?.development_override)||props.armPending} onClick={props.onArm}>允许下一次定时验证</Button>
          <Button danger loading={props.cancelPending} disabled={!schedule?.development_override||props.cancelPending} onClick={props.onCancel}>撤销一次性授权</Button></Space>
      </section>}
      <section className="settings-section">
        <h3>手动验证圆屏问候</h3>
        <p className="subtle">每次点击只尝试一次，仍遵守许可、时段、勿扰、频率和设备状态。</p>
        <Input aria-label="测试问候内容" maxLength={80} showCount value={props.testText} onChange={event=>props.onTestText(event.target.value)}/>
        <Button loading={props.testPending} disabled={!draft.enabled||props.dirty||props.testPending||!props.testText.trim()||props.testText!==props.testText.trim()} onClick={props.onTest}>发送一次测试问候</Button>
      </section>
    </Space>},
  ];

  return <>
    <section className="proactive-overview" aria-label="主动交流概览">
      <div><small>主动联系</small><strong className={draft.enabled?'is-positive':''}>{draft.enabled?'已允许':'已关闭'}</strong></div>
      <div><small>周期问候</small><strong>{draft.automatic_enabled?proactiveFrequencyText(draft.automatic_interval_seconds):'已关闭'}</strong></div>
      <div><small>允许时段</small><strong>{minuteText(draft.allowed_start_minute)}–{minuteText(draft.allowed_end_minute)}</strong></div>
      <div><small>等待回应</small><strong className={schedule?.awaiting_user_response?'is-warning':''}>{schedule?.awaiting_user_response?'是':'否'}</strong></div>
    </section>
    {props.testNotice&&<Alert role="status" type="info" showIcon title={props.testNotice}/>}

    <section className="settings-section proactive-policy-section">
      <h3>常用设置</h3>
      <div className="setting-line"><span>允许助手主动联系</span><Switch aria-label="允许主动联系" checked={draft.enabled}
        onChange={enabled=>props.onChange({enabled,...(!enabled?{automatic_enabled:false,topic_enabled:false,dynamic_greeting_enabled:false}:{})})}/></div>
      <div className="setting-line"><span>开启周期问候</span><Switch aria-label="后台定时问候" disabled={!draft.enabled} checked={draft.automatic_enabled}
        onChange={automatic_enabled=>props.onChange({automatic_enabled,...(!automatic_enabled?{topic_enabled:false,dynamic_greeting_enabled:false}:{})})}/></div>
      <label htmlFor="proactive-frequency">主动交流频率</label>
      <InputNumber id="proactive-frequency" aria-label="主动交流频率（分钟）" min={1} max={1440} step={1} value={intervalMinutes} onChange={setFrequency}/>
      <small>{proactiveFrequencyText(draft.automatic_interval_seconds)}；可设置 1 分钟到 24 小时。语音可说“把主动交流频率改成每十分钟一次”。</small>
      {!dailyMode&&<small>保存并开启后会从下一个允许分钟自动开始，不需要设置周期锚点。</small>}
      {!draft.automatic_enabled&&<Alert type="info" showIcon title="频率已设置，但周期问候尚未开启" description="打开上方开关并保存后，短周期会从下一个允许分钟自动开始。"/>}
      {intervalMinutes<=5&&<Alert type="warning" showIcon title="当前是高频主动交流" description="一分钟级频率可能频繁打断你；上一条仍待回应、勿扰、设备忙碌或不在允许时段时仍会停止播报。"/>}
      <label htmlFor="proactive-greeting">问候内容</label>
      <Input id="proactive-greeting" maxLength={80} showCount value={draft.greeting_text} onChange={event=>props.onChange({greeting_text:event.target.value})}/>
      {dailyMode&&draft.automatic_enabled&&!scheduleInsideWindow&&<Alert type="error" showIcon title="每日问候时刻必须位于允许时段内"/>}
      {schedule?.awaiting_user_response&&<Alert type="info" showIcon title="正在等待你回应上一条主动问候" description="真正说出并保存一条新消息后，后续时间槽才会继续尝试。"/>}
      {dailyMode&&schedule?.user_chatted_today&&<Alert type="info" showIcon title="今天已经聊过，今天的每日问候会跳过" description="改成短于 24 小时的间隔后，今日对话不再跳过整天；其他护栏仍保留。"/>}
      {props.scheduleFailed&&<Alert type="error" showIcon title="暂时无法读取当前调度状态"/>}
      <Space wrap><Button type="primary" loading={props.savePending} disabled={!props.dirty||draft.allowed_weekdays.length===0||draft.allowed_start_minute===draft.allowed_end_minute||(dailyMode&&draft.automatic_enabled&&!scheduleInsideWindow)||!draft.greeting_text.trim()||draft.greeting_text!==draft.greeting_text.trim()} onClick={props.onSave}>保存主动交流设置</Button>
        <Button disabled={!props.dirty||props.savePending} onClick={props.onDiscard}>放弃修改</Button></Space>
      {props.notice&&<p role="status">{props.notice}</p>}
    </section>
    <Collapse ghost items={advanced}/>
  </>;
}
