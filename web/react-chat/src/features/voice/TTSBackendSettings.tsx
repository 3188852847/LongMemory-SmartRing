import {useEffect,useMemo,useState} from 'react';
import {Alert,Button,Descriptions,Select,Space,Tag} from 'antd';
import {ApiError,type ChatApi,type TTSBackendId,type TTSBackends} from '../../api';

export function ttsBackendFailure(error:unknown,phase:'read'|'write') {
  if(error instanceof ApiError){
    if(error.code==='tts_backends_disabled')return '当前进程没有启用 TTS 后端选择。请从统一启动面板启动完整控制台。';
    if(error.code==='invalid_tts_backend')return '选择的 TTS 后端无效，请重新读取后再保存。';
  }
  return phase==='write'?'下次启动选择未确认保存，请重新读取。':'暂时无法读取 TTS 后端状态。';
}

export function TTSBackendSettings({api,disabled}:{api:ChatApi;disabled:boolean}){
  const [data,setData]=useState<TTSBackends>();
  const [selected,setSelected]=useState<TTSBackendId>('cosyvoice3');
  const [advanced,setAdvanced]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    if(disabled)return;
    let active=true;
    api.request<TTSBackends>('/api/tts-backends').then(value=>{if(active){setData(value);setSelected(value.next_start_backend??'edge');}})
      .catch(reason=>active&&setError(ttsBackendFailure(reason,'read')));
    return()=>{active=false;};
  },[api,disabled]);
  const option=useMemo(()=>data?.backends?.find(item=>item.id===selected),[data,selected]);
  async function save(){
    setSaving(true);setError('');
    try{setData(await api.request<TTSBackends>('/api/tts-backends/selection','PUT',{backend:selected}));}
    catch(reason){setError(ttsBackendFailure(reason,'write'));}
    finally{setSaving(false);}
  }
  return <section className="settings-subsection" aria-labelledby="tts-backend-title">
    <h3 id="tts-backend-title">圆屏声音后端</h3>
    <p>这里保存下次统一启动使用的 TTS。不会在回答中途切换，也不会立即启动或卸载本地模型。</p>
    {error&&<Alert type="error" showIcon title="TTS 后端选择未完成" description={error}/>}
    <Space wrap>
      <span>下次圆屏语音启动</span>
      <Select aria-label="圆屏声音后端" value={selected} onChange={setSelected} style={{minWidth:300}}
        options={data?.backends?.filter(item=>advanced||item.id==='cosyvoice3'||item.id===selected).map(item=>({value:item.id,label:item.id==='cosyvoice3'?item.label:`${item.label}（兼容）`}))}/>
      <Button type="primary" loading={saving} disabled={disabled||!data?.enabled||selected===data.next_start_backend} onClick={()=>void save()}>保存下次启动选择</Button>
    </Space>
    <p>日用声音集中使用 CosyVoice 3。旧引擎保留兼容配置和实验记录。</p>
    <Button type="text" disabled={saving} onClick={()=>setAdvanced(!advanced)}>{advanced?'收起兼容声音引擎':'高级：兼容声音引擎'}</Button>
    {option&&<Descriptions bordered size="small" column={1} items={[
      {key:'description',label:'适用性',children:option.description},
      {key:'runtime',label:'本次语音',children:data?.voice_running?(data.current_backend===option.id?<Tag color="processing">正在使用</Tag>:'不是当前后端'):<Tag>未由当前启动器运行</Tag>},
      {key:'service',label:'额外本地服务',children:option.local_service?'需要，启动器会在启动前检查':'不需要'},
    ]}/>}
    {data?.restart_required&&<Alert type="warning" showIcon title="等待重启生效" description="当前圆屏语音仍在使用启动时的后端。请用统一启动面板停止服务后重新启动；面板会在启动瞬间读取这里保存的选择。"/>}
  </section>;
}
