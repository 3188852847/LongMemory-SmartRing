import {useEffect, useState} from 'react';
import {Alert, Button, Radio, Space} from 'antd';
import {ApiError, ChatApi} from './api';

type Profile='normal'|'noisy'|'close_talk';
interface Status {
  profile:Profile|'custom';
  values:{threshold:number;threshold_low:number;min_silence_duration_ms:number};
  digest:string;
  runtime:'unverified';
}

const options=[
  {value:'normal', title:'普通环境', detail:'阈值 0.50 / 0.30，停顿 600 ms；适合安静的个人空间。'},
  {value:'noisy', title:'嘈杂环境', detail:'阈值 0.70 / 0.45，停顿 650 ms；减少远处人声和环境声误触发。'},
  {value:'close_talk', title:'近讲严格', detail:'阈值 0.82 / 0.55，停顿 700 ms；需要靠近圆屏说话。'},
] as const;

export function vadSettingsFailure(error:unknown) {
  if (!(error instanceof ApiError)) return '拾音配置操作未完成，请重新读取。';
  if (error.code==='vad_not_enabled') return '当前控制台没有启用小智配置能力，请从统一启动面板启动。';
  return '配置可能已变化或未能安全写入；已停止自动重试，请重新读取。';
}

export function VADSettings({api,disabled}:{api:ChatApi;disabled:boolean}) {
  const [status,setStatus]=useState<Status>();
  const [draft,setDraft]=useState<Profile>('noisy');
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState('');
  async function load() {
    setBusy(true);setNotice('');
    try {const value=await api.request<Status>('/api/vad-settings');setStatus(value);if(value.profile!=='custom')setDraft(value.profile);}
    catch(error){setStatus(undefined);setNotice(vadSettingsFailure(error));}
    finally{setBusy(false);}
  }
  useEffect(()=>{if(!disabled)void load();},[disabled]);
  async function save(){
    if(!status)return;
    setBusy(true);setNotice('');
    try {
      const value=await api.request<Status>('/api/vad-settings','PUT',{profile:draft,expected_digest:status.digest});
      setStatus(value);setNotice('拾音档位已保存。请停止并重新启动圆屏语音，新档位才会被运行中的小智加载。');
    } catch(error){setStatus(undefined);setNotice(vadSettingsFailure(error));}
    finally{setBusy(false);}
  }
  return <section className="settings-subsection" aria-labelledby="vad-title">
    <h3 id="vad-title">拾音灵敏度</h3>
    <p>调整语音活动检测（VAD）的触发门槛。它能减少旁人误触发，但不能识别“说话的人是不是你”。</p>
    {notice&&<Alert type={notice.includes('已保存')?'success':'warning'} showIcon title={notice}/>}
    {status?.profile==='custom'&&<Alert type="warning" showIcon title="当前数值不匹配三个受控预设" description="页面不会猜测它属于哪一档；选择预设并保存后才会替换三个数值。"/>}
    {!status&&!notice&&<p role="status">正在读取拾音配置…</p>}
    <Radio.Group aria-label="拾音灵敏度" value={draft} disabled={disabled||busy||!status} onChange={event=>setDraft(event.target.value)}>
      <Space orientation="vertical">
        {options.map(item=><Radio key={item.value} value={item.value}><strong>{item.title}</strong><br/><small>{item.detail}</small></Radio>)}
      </Space>
    </Radio.Group>
    <Space wrap>
      <Button disabled={disabled||busy} onClick={()=>void load()}>重新读取</Button>
      <Button type="primary" disabled={disabled||busy||!status||draft===status.profile} onClick={()=>void save()}>保存拾音档位</Button>
    </Space>
  </section>;
}
