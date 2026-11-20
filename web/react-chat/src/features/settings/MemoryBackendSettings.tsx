import {useEffect, useState} from 'react';
import {Alert} from 'antd';
import type {ChatApi, MemoryBackends} from '../../api';

export function MemoryBackendSettings({api, disabled}: {api:ChatApi; disabled:boolean}) {
  const [data, setData] = useState<MemoryBackends>();
  useEffect(() => {
    let active = true;
    setData(undefined);
    if (!disabled) api.request<MemoryBackends>('/api/memory-backends')
      .then(value => {if (active) setData(value);})
      .catch(() => {if (active) setData({enabled:false});});
    return () => {active = false;};
  }, [api, disabled]);

  const status = disabled || data?.enabled === false ? '当前服务状态不可用。'
    : !data ? '正在读取服务状态…'
    : data.current_backend === 'hy_memory' ? '当前服务正在使用 Hy-Memory。'
    : '当前服务仍使用旧配置，下次从启动面板开启陪伴时使用 Hy-Memory。';
  return <Alert type="info" showIcon title="Hy-Memory"
    description={<>网页聊天和圆屏对话共享长期记忆。{status}</>}/>;
}
