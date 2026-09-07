import {useState} from 'react';
import {Alert, Button, Descriptions, Tag} from 'antd';
import {type ChatApi, type Config, type ModelHealth} from './api';
import {modelFailure} from './modelHealth';

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
  const health = config?.model_health;
  async function check() {
    if (checking || config?.provider !== 'openai_compatible') return;
    setChecking(true); setRequestError('');
    try {onHealth(await api.request<ModelHealth>('/api/chat-model/check', 'POST', {}));}
    catch (error) {setRequestError(String(error));}
    finally {setChecking(false);}
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
    {requestError && <Alert className="settings-model-alert" type="error" showIcon title="检测请求未完成" description={requestError}/>} 
    {config?.insecure_model_transport && <Alert className="settings-model-alert" type="warning" showIcon
      title="当前配置使用 HTTP 明文传输" description="凭据、问题和检索证据可能被链路观察；只在你已接受风险的校园网使用。"/>}
    <Button type="primary" loading={checking} disabled={disabled || config?.provider !== 'openai_compatible'} onClick={() => void check()}>
      检测当前模型连接
    </Button>
    <p className="subtle">检测只发送固定合成短句，不读取或写入个人记忆，不自动重试，也不代表圆屏语音链路已经可用。修改 `.env` 后必须重启服务，本页才会显示新配置。</p>
  </>;
}
