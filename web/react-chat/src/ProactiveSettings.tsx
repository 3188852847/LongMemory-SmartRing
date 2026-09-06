import {useEffect, useMemo, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Alert, Button, Checkbox, Input, InputNumber, Space, Switch} from 'antd';
import {ApiError, ChatApi, type ProactivePolicy} from './api';

const DAYS = ['周一','周二','周三','周四','周五','周六','周日'].map((label, value) => ({label, value}));
const minuteText = (value:number) => `${String(Math.floor(value / 60)).padStart(2,'0')}:${String(value % 60).padStart(2,'0')}`;
const parseMinute = (value:string) => {const [hour, minute] = value.split(':').map(Number); return hour * 60 + minute;};

/** 编辑明确许可边界；保存设置不会调用模型、创建候选或向设备投递。 */
export function ProactiveSettings({api, ready}:{api:ChatApi; ready:boolean}) {
  const client = useQueryClient();
  const query = useQuery({queryKey:['proactive-policy'], queryFn:() => api.request<ProactivePolicy>('/api/proactive-policy'), enabled:ready});
  const [draft, setDraft] = useState<ProactivePolicy>();
  const [notice, setNotice] = useState('');
  useEffect(() => {if (query.data) setDraft({...query.data, allowed_weekdays:[...query.data.allowed_weekdays]});}, [query.data]);
  const dirty = useMemo(() => Boolean(draft && query.data && JSON.stringify(draft) !== JSON.stringify(query.data)), [draft, query.data]);
  const mutation = useMutation({
    mutationFn:(value:ProactivePolicy) => api.request<ProactivePolicy>('/api/proactive-policy', 'PUT', {
      expected_revision:value.revision, enabled:value.enabled, utc_offset_minutes:value.utc_offset_minutes,
      allowed_weekdays:value.allowed_weekdays, allowed_start_minute:value.allowed_start_minute,
      allowed_end_minute:value.allowed_end_minute, daily_limit:value.daily_limit,
      minimum_interval_seconds:value.minimum_interval_seconds,
      maximum_lifetime_seconds:value.maximum_lifetime_seconds, quiet_until:value.quiet_until,
    }),
    onSuccess:value => {client.setQueryData(['proactive-policy'], value); setDraft({...value, allowed_weekdays:[...value.allowed_weekdays]}); setNotice('设置已保存；后台主动联系仍未接入。');},
    onError:error => {setNotice(error instanceof ApiError && error.code === 'proactive_settings_conflict' ? '设置已被另一个页面修改，请重新读取后再保存。' : '保存失败，未自动重试。'); void client.invalidateQueries({queryKey:['proactive-policy']});},
  });
  const change = (patch:Partial<ProactivePolicy>) => draft && setDraft({...draft, ...patch});
  if (query.isError) return <Alert type="error" showIcon title="主动交流设置不可用" description="请确认已选择当前版本的个人数据库。"/>;
  if (query.isLoading || !draft) return <Alert type="info" showIcon title="正在读取主动交流设置…"/>;
  const quietActive = draft.quiet_until && new Date(draft.quiet_until).getTime() > Date.now();
  return <Space orientation="vertical" style={{width:'100%'}}>
    <Alert type={draft.enabled ? 'warning' : 'success'} showIcon
      title={draft.enabled ? '许可总开关已打开，但执行编排尚未接入' : '主动交流当前关闭'}
      description="本页只保存许可边界。现阶段不会因为打开开关就自动联系，也不代表圆屏投递已经实机验收。"/>
    <div className="setting-line"><span>允许主动联系</span><Switch aria-label="允许主动联系" checked={draft.enabled} onChange={enabled => change({enabled})}/></div>
    <label>允许星期</label>
    <Checkbox.Group aria-label="允许星期" options={DAYS} value={draft.allowed_weekdays} onChange={values => change({allowed_weekdays:values.map(Number).sort()})}/>
    <div className="proactive-fields">
      <div><label htmlFor="proactive-start">开始时间</label><Input id="proactive-start" type="time" value={minuteText(draft.allowed_start_minute)} onChange={event => change({allowed_start_minute:parseMinute(event.target.value)})}/></div>
      <div><label htmlFor="proactive-end">结束时间</label><Input id="proactive-end" type="time" value={minuteText(draft.allowed_end_minute)} onChange={event => change({allowed_end_minute:parseMinute(event.target.value)})}/></div>
      <div><label htmlFor="proactive-daily">每天最多次数</label><InputNumber id="proactive-daily" min={1} max={20} value={draft.daily_limit} onChange={value => value && change({daily_limit:value})}/></div>
      <div><label htmlFor="proactive-gap">最短间隔（小时）</label><InputNumber id="proactive-gap" min={0} max={168} value={draft.minimum_interval_seconds / 3600} onChange={value => value !== null && change({minimum_interval_seconds:Math.round(value * 3600)})}/></div>
    </div>
    <p className="subtle">时区：UTC{draft.utc_offset_minutes >= 0 ? '+' : ''}{draft.utc_offset_minutes / 60}（第一版固定偏移）；消息超过 {draft.maximum_lifetime_seconds / 60} 分钟就不再投递。</p>
    <div className="setting-line"><span>{quietActive ? `临时勿扰至 ${new Date(draft.quiet_until!).toLocaleString()}` : '临时勿扰未开启'}</span><Space><Button onClick={() => change({quiet_until:new Date(Date.now() + 60 * 60 * 1000).toISOString()})}>勿扰 1 小时</Button><Button disabled={!draft.quiet_until} onClick={() => change({quiet_until:null})}>解除勿扰</Button></Space></div>
    <Space><Button type="primary" loading={mutation.isPending} disabled={!dirty || draft.allowed_weekdays.length === 0 || draft.allowed_start_minute === draft.allowed_end_minute} onClick={() => mutation.mutate(draft)}>保存主动交流设置</Button><Button disabled={!dirty || mutation.isPending} onClick={() => {setDraft({...query.data!, allowed_weekdays:[...query.data!.allowed_weekdays]}); setNotice('已放弃未保存修改。');}}>放弃修改</Button></Space>
    {notice && <p role="status">{notice}</p>}
  </Space>;
}
