import {useEffect, useMemo, useState} from 'react';
import {Alert, Button, Descriptions, Select, Space, Tag} from 'antd';
import {ApiError, type ChatApi, type MemoryBackends, type MemoryBackendOption} from '../../api';

export function memoryBackendFailure(error: unknown, phase: 'read'|'write') {
  if (error instanceof ApiError) {
    if (error.code === 'memory_backends_disabled') return '当前进程未启用记忆后端切换。请通过统一启动面板启动完整控制台。';
    if (error.code === 'invalid_memory_backend') return '选择的记忆后端无效。请重新读取可用选项后再保存。';
  }
  return phase === 'write'
    ? '记忆后端选择未确认保存。请重新读取当前选择后再决定是否重试。'
    : '暂时无法读取记忆后端状态。请检查控制台服务；没有自动重试写操作。';
}

/** 只选择圆屏下次启动的后端；不热切换，也不复制或清空任何记忆库。 */
export function MemoryBackendSettings({api, disabled}: {api:ChatApi; disabled:boolean}) {
  const [data, setData] = useState<MemoryBackends>();
  const [selected, setSelected] = useState<MemoryBackendOption['id']>('longmemory');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (disabled) return;
    let active = true;
    api.request<MemoryBackends>('/api/memory-backends').then(value => {
      if (!active) return;
      setData(value);
      setSelected(value.next_start_backend ?? 'longmemory');
    }).catch(reason => active && setError(memoryBackendFailure(reason, 'read')));
    return () => {active = false;};
  }, [api, disabled]);
  const option = useMemo(() => data?.backends?.find(item => item.id === selected), [data, selected]);
  async function save() {
    setSaving(true); setError('');
    try {
      setData(await api.request<MemoryBackends>('/api/memory-backends/selection', 'PUT', {backend:selected}));
    } catch (reason) {setError(memoryBackendFailure(reason, 'write'));}
    finally {setSaving(false);}
  }
  return <>
    <Alert type="info" showIcon title="这里切换的是圆屏长期记忆，不是圆屏固件"
      description="ASR、回答模型、人格、TTS 和设备控制保持不变。切换只在停止并重新启动服务后生效，各后端不会共享或迁移数据。"/>
    {error && <Alert className="settings-model-alert" type="error" showIcon title="记忆后端状态读取失败" description={error}/>}
    <Space wrap className="settings-model-alert">
      <span>下次圆屏启动</span>
      <Select aria-label="圆屏记忆后端" value={selected} onChange={setSelected} style={{minWidth:280}}
        options={data?.backends?.map(item => ({value:item.id,label:item.label}))}/>
      <Button type="primary" loading={saving} disabled={disabled || !data?.enabled} onClick={() => void save()}>保存选择</Button>
    </Space>
    {option && <Descriptions bordered size="small" column={1} items={[
      {key:'description',label:'处理方式',children:option.description},
      {key:'persistent',label:'跨会话保存',children:option.persistent ? <Tag color="success">保存</Tag> : <Tag>不保存</Tag>},
      {key:'provider',label:'小智提供器',children:<code>{option.provider}</code>},
      {key:'current',label:'本次运行',children:data?.current_backend === option.id ? <Tag color="processing">正在使用</Tag> : '不是当前后端'},
      {key:'disk',label:'小智磁盘配置',children:data?.xiaozhi?.status === 'configured' ? <Tag color="success">已匹配</Tag> : <Tag color="warning">等待启动器同步</Tag>},
    ]}/>}
    {data?.restart_required && <Alert className="settings-model-alert" type="warning" showIcon title="需要重新启动"
      description="保存只改变非敏感的下次启动指针；统一启动器会在端口空闲后备份小智配置并应用。"/>}
    <Alert className="settings-model-alert" type="warning" showIcon title="比较结果不能只看主观回答"
      description="同一问题、模型、人格和 TTS 下，还要记录记忆处理耗时、首音频延迟、跨会话召回、错误引用与拒答。小智摘要目前不具备 LongMemory 的逐条来源和纠错链。"/>
  </>;
}
