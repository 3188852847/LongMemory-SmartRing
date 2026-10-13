import {useEffect, useMemo, useState} from 'react';
import {Alert, Button, Descriptions, Divider, Form, Input, InputNumber, Select, Space, Switch, Tag} from 'antd';
import {type ChatApi, type Config, type ModelHealth, type ModelProfile, type ModelProfiles, type VoiceModelHealth} from '../../api';
import {modelFailure} from './modelHealth';
import {settingsFailure} from './settingsFailure';

function healthLabel(health: ModelHealth | undefined) {
  if (health?.state === 'available') return <Tag color="success">最近验证可用</Tag>;
  if (health?.state === 'unavailable') return <Tag color="error">最近验证失败</Tag>;
  if (health?.state === 'not_applicable') return <Tag>离线替身</Tag>;
  return <Tag color="warning">尚未验证</Tag>;
}

/** 集中展示实际启动配置；检测只发合成短句，不读取记忆，也不会自动重试。 */
export function ModelConnectionSettings({api, config, disabled, onHealth}: {
  api: ChatApi; config?: Config; disabled: boolean; onHealth: (health: ModelHealth) => void;
}) {
  const [checking, setChecking] = useState(false);
  const [requestError, setRequestError] = useState('');
  const [profiles, setProfiles] = useState<ModelProfiles>();
  const [selected, setSelected] = useState<'campus'|'official'>('official');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [voiceSelected, setVoiceSelected] = useState<'campus'|'official'>('official');
  const [voiceSaving, setVoiceSaving] = useState(false);
  const [voiceChecking, setVoiceChecking] = useState(false);
  const [voiceHealth, setVoiceHealth] = useState<VoiceModelHealth>();
  const [form] = Form.useForm();
  const allowHttp = Form.useWatch('allow_http', form);
  const health = config?.model_health;
  const profile = useMemo(() => profiles?.profiles?.find(item => item.id === selected), [profiles, selected]);

  useEffect(() => {
    if (disabled) return;
    let active = true;
    api.request<ModelProfiles>('/api/model-profiles').then(result => {
      if (!active) return;
      setProfiles(result);
      const choice = result.next_start_profile ?? 'official';
      setSelected(choice);
      setVoiceSelected(result.voice_next_start_profile ?? result.voice?.selected_profile ?? choice);
    }).catch(error => active && setRequestError(settingsFailure(error, 'read')));
    return () => {active = false;};
  }, [api, disabled]);

  useEffect(() => {
    if (!profile) return;
    form.setFieldsValue({...profile, api_key:''});
    setSaved(false);
  }, [form, profile]);
  async function check() {
    if (checking || config?.provider !== 'openai_compatible') return;
    setChecking(true); setRequestError('');
    try {onHealth(await api.request<ModelHealth>('/api/chat-model/check', 'POST', {}));}
    catch (error) {setRequestError(settingsFailure(error, 'read'));}
    finally {setChecking(false);}
  }
  async function save(values: {base_url:string; model:string; api_key?:string; timeout_seconds:number; max_tokens:number; allow_http:boolean}) {
    setSaving(true); setSaved(false); setRequestError('');
    try {
      const result = await api.request<ModelProfiles>(`/api/model-profiles/${selected}`, 'PUT', {...values, activate:true});
      setProfiles(result); form.setFieldValue('api_key', ''); setSaved(true);
    } catch (error) {setRequestError(settingsFailure(error, 'write'));}
    finally {setSaving(false);}
  }
  async function saveVoiceSelection() {
    setVoiceSaving(true); setRequestError(''); setVoiceHealth(undefined);
    try {
      const voice = await api.request<NonNullable<ModelProfiles['voice']>>('/api/model-profiles/voice/selection', 'PUT', {profile:voiceSelected});
      setProfiles(current => current ? {...current, voice_next_start_profile:voice.selected_profile, voice} : current);
    } catch (error) {setRequestError(settingsFailure(error, 'write'));}
    finally {setVoiceSaving(false);}
  }
  async function checkVoice() {
    setVoiceChecking(true); setRequestError('');
    try {setVoiceHealth(await api.request<VoiceModelHealth>('/api/model-profiles/voice/check', 'POST', {}));}
    catch (error) {setRequestError(settingsFailure(error, 'read'));}
    finally {setVoiceChecking(false);}
  }
  return <>
    <Descriptions bordered size="small" column={1} items={[
      {key:'provider', label:'连接方式', children:config?.provider ?? '未读取'},
      {key:'model', label:'模型名称', children:config?.model ?? '未读取'},
      {key:'endpoint', label:'服务地址（不含密钥）', children:config?.model_endpoint ?? '离线替身未使用网络地址'},
      {key:'transport', label:'传输', children:config?.insecure_model_transport ? <Tag color="warning">HTTP 明文</Tag> : <Tag color="success">HTTPS 或本机</Tag>},
      {key:'health', label:'本进程状态', children:healthLabel(health)},
      {key:'checked', label:'最近检测', children:health?.checked_at ? new Date(health.checked_at).toLocaleString() : '本进程尚未检测'},
    ]}/>
    {health?.state === 'unavailable' && <Alert className="settings-model-alert" type="error" showIcon
      title="当前模型连接不可用" description={modelFailure(health.code) ?? '模型调用失败；未返回供应商正文或密钥。'}/>} 
    {requestError && <Alert className="settings-model-alert" type="error" showIcon title="模型设置操作未完成" description={requestError}/>}
    {config?.insecure_model_transport && <Alert className="settings-model-alert" type="warning" showIcon
      title="当前配置使用 HTTP 明文传输" description="凭据、问题和检索证据可能被链路观察；只在你已接受风险的校园网使用。"/>}
    <Button type="primary" loading={checking} disabled={disabled || config?.provider !== 'openai_compatible'} onClick={() => void check()}>
      检测当前模型连接
    </Button>
    <p className="subtle">检测只发送固定合成短句，不读取或写入个人记忆，不自动重试，也不代表圆屏语音链路已经可用。</p>
    <Divider>网页服务：下次启动配置</Divider>
    {profiles?.enabled === false && <Alert type="warning" showIcon title="当前启动方式未开放模型配置管理"/>}
    {profiles?.enabled && <>
      <Space wrap>
        <span>配置档</span>
        <Select aria-label="模型配置档" value={selected} onChange={setSelected} style={{minWidth:220}}
          options={profiles.profiles?.map(item => ({value:item.id, label:item.label}))}/>
        {profiles.current_profile === selected ? <Tag color="processing">当前进程</Tag> : null}
        {profiles.next_start_profile === selected ? <Tag color="success">下次启动</Tag> : null}
      </Space>
      <Form form={form} layout="vertical" onFinish={values => void save(values)} className="model-profile-form">
        <Form.Item label="服务地址" name="base_url" rules={[{required:true,message:'请填写兼容接口的 /v1 根地址'}]}>
          <Input placeholder="https://api.deepseek.com/v1" autoComplete="off"/>
        </Form.Item>
        <Form.Item label="模型名称" name="model" rules={[{required:true,message:'请填写模型名称'}]}>
          <Input autoComplete="off"/>
        </Form.Item>
        <Form.Item label={profile?.api_key_configured ? 'API Key（已配置；留空保留原值）' : 'API Key（尚未配置）'} name="api_key">
          <Input.Password autoComplete="new-password" placeholder="只在覆盖时填写；页面不会读取已有 Key"/>
        </Form.Item>
        <Space wrap align="start">
          <Form.Item label="超时（秒）" name="timeout_seconds" rules={[{required:true}]}><InputNumber min={1} max={300}/></Form.Item>
          <Form.Item label="最大输出 Token" name="max_tokens" rules={[{required:true}]}><InputNumber min={1} max={32768}/></Form.Item>
          <Form.Item label="允许 HTTP 明文" name="allow_http" valuePropName="checked"><Switch/></Form.Item>
        </Space>
        {allowHttp && <Alert type="warning" showIcon title="HTTP 会明文传输 Key、对话和记忆证据" description="只应为已知的校园网服务开启；官方 DeepSeek 应使用 HTTPS。"/>}
        <Button htmlType="submit" type="primary" loading={saving} disabled={disabled}>保存并设为下次启动</Button>
      </Form>
      {saved && <Alert className="settings-model-alert" type="success" showIcon title="网页模型配置已保存" description="请从启动面板重新启动服务。当前进程不会热切换；圆屏使用下方独立选择。"/>}
      {profiles.restart_required && <Alert className="settings-model-alert" type="info" showIcon title="等待重启生效" description={`当前进程：${profiles.current_profile === 'official' ? '官方 DeepSeek' : '学校模型'}；下次启动：${profiles.next_start_profile === 'official' ? '官方 DeepSeek' : '学校模型'}。`}/>}
      <Divider>圆屏语音：下次启动配置</Divider>
      <Space wrap>
        <span>圆屏模型</span>
        <Select aria-label="圆屏模型配置档" value={voiceSelected} onChange={setVoiceSelected} style={{minWidth:220}}
          options={profiles.profiles?.map(item => ({value:item.id, label:item.label}))}/>
        <Button loading={voiceSaving} disabled={disabled || !profiles.voice?.enabled} onClick={() => void saveVoiceSelection()}>保存圆屏选择</Button>
        <Button loading={voiceChecking} disabled={disabled || !profiles.voice?.enabled} onClick={() => void checkVoice()}>检测圆屏模型连接</Button>
      </Space>
      {profiles.voice?.enabled ? <Descriptions className="settings-model-alert" bordered size="small" column={1} items={[
        {key:'voice-state',label:'小智磁盘配置',children:profiles.voice.status === 'configured' ? <Tag color="success">已匹配所选档案</Tag> : <Tag color="warning">等待启动器同步</Tag>},
        {key:'voice-model',label:'当前写入小智的模型',children:profiles.voice.configured_model || '未读取'},
        {key:'voice-endpoint',label:'当前写入小智的地址',children:profiles.voice.configured_base_url || '未读取'},
      ]}/> : <Alert className="settings-model-alert" type="warning" showIcon title="无法检查圆屏模型配置" description="请核对启动面板中的小智目录；未读取或显示私有 Key。"/>}
      {profiles.voice?.status === 'restart_pending' && <Alert className="settings-model-alert" type="info" showIcon title="圆屏选择尚未应用" description="从启动面板停止并重新启动圆屏语音；启动器会先备份小智 YAML，再只同步模型地址、名称和 Key。"/>}
      {voiceHealth?.state === 'available' && <Alert className="settings-model-alert" type="success" showIcon title="圆屏所选模型连接可用" description="固定合成短句获得了非空响应；这不代表语音、记忆或回答质量已验收。"/>}
      {voiceHealth?.state === 'unavailable' && <Alert className="settings-model-alert" type="error" showIcon title="圆屏所选模型连接失败" description={modelFailure(voiceHealth.code) ?? '模型配置或调用失败；未返回供应商正文或密钥。'}/>}
      <p className="subtle">圆屏检测直接检查它所选的档案，不依赖网页当前进程。保存选择不会热改运行中的小智；下次统一启动时才安全同步并生效。</p>
    </>}
  </>;
}
