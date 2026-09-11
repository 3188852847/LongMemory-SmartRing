import {useState} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Alert, Button, Descriptions, Select, Space, Table, Tag} from 'antd';
import {ApiError, ChatApi, type TTSBenchmarkIndex, type TTSBenchmarkResult} from './api';
import {SpeechPlayer} from './SpeechPlayer';

const localityLabels:Record<string,string>={local:'本机',remote:'联网',browser:'浏览器',device:'设备端'};
const controlLabels:Record<string,string>={voice_selection:'选择音色',reference_voice:'参考音色',style_prompt:'表达指令',speaking_rate:'语速',volume:'音量',emotion:'情绪'};

function failureText(error:unknown) {
  if (error instanceof ApiError) {
    if (error.code==='speech_busy') return '声音服务正在处理其他请求；本次没有排队或重试。';
    if (error.code==='tts_service_unavailable') return '当前 TTS 没有生成有效音频；请先核对声音服务。';
    if (error.code==='voice_not_enabled') return '当前控制台没有启用小智声音配置。';
  }
  return '测试没有完成；未自动重试，也没有写入聊天或记忆。';
}

/** 用固定合成文本测量当前实际适配链路，避免拿供应商宣传数字替代本机结果。 */
export function TTSBenchmarkPanel({api,enabled}:{api:ChatApi;enabled:boolean}) {
  const [caseId,setCaseId]=useState('short_reply');
  const index=useQuery({queryKey:['tts-benchmark'],queryFn:()=>api.request<TTSBenchmarkIndex>('/api/tts-benchmark'),enabled});
  const run=useMutation({
    mutationFn:()=>api.request<TTSBenchmarkResult>('/api/tts-benchmark','POST',{case_id:caseId}),
    onSuccess:()=>void index.refetch(),
  });
  const capability=index.data?.capabilities;
  const result=run.data;
  return <section className="tts-benchmark" aria-label="TTS 测试台">
    <h3>TTS 测试台</h3>
    <p>只发送下方合成文本，不读取聊天、个人记忆或用户音频；每次只运行一项，失败不重试。</p>
    {index.isError&&<Alert type="warning" showIcon title="无法读取 TTS 测试能力" description={failureText(index.error)}/>}
    {capability&&<Space wrap>
      <Tag color="cyan">{capability.display_name}</Tag>
      <Tag>{localityLabels[capability.locality]??capability.locality}</Tag>
      <Tag color={capability.delivery_modes.includes('audio_stream')?'green':'gold'}>{capability.delivery_modes.includes('audio_stream')?'音频流式':'完整音频缓冲'}</Tag>
      <Tag color={capability.cancellation==='cooperative'?'green':'default'}>{capability.cancellation==='cooperative'?'支持取消生成':'不能取消生成'}</Tag>
      {capability.controls.map(item=><Tag key={item}>{controlLabels[item]??item}</Tag>)}
    </Space>}
    <Space wrap className="settings-model-alert">
      <Select aria-label="TTS 测试文本" value={caseId} disabled={!index.data||run.isPending} style={{minWidth:220}}
        options={(index.data?.cases??[]).map(item=>({value:item.id,label:`${item.label} · ${item.text_chars} 字`}))}
        onChange={value=>{setCaseId(value);run.reset();}}/>
      <Button type="primary" loading={run.isPending} disabled={!index.data||run.isPending} onClick={()=>run.mutate()}>运行一次测试</Button>
    </Space>
    {index.data&&<p className="subtle">{index.data.cases.find(item=>item.id===caseId)?.text}<br/>{index.data.cases.find(item=>item.id===caseId)?.purpose}</p>}
    {index.data&&<div>
      <SpeechPlayer api={api} text={index.data.cases.find(item=>item.id===caseId)?.text??''}/>
      <small className="subtle">试听与“运行一次测试”是两次独立合成；试听用于听感，测试用于记录指标。</small>
    </div>}
    {run.isError&&<Alert type="warning" showIcon title="TTS 测试未完成" description={failureText(run.error)}/>}
    {result&&<>
      <Descriptions bordered size="small" column={{xs:1,sm:2}} items={[
        {key:'backend',label:'实际后端',children:result.capabilities?.display_name??result.backend},
        {key:'delivery',label:'当前交付方式',children:result.adapter_delivery==='buffered'?'完整音频缓冲':'音频流式'},
        {key:'first',label:'首个可用音频',children:`${result.first_audio_available_ms.toFixed(0)} ms`},
        {key:'total',label:'本次完成',children:`${result.completed_ms.toFixed(0)} ms`},
        {key:'bytes',label:'音频大小',children:`${result.audio_bytes.toLocaleString()} bytes`},
        {key:'wave',label:'WAV 检查',children:result.wave?`${result.wave.duration_seconds.toFixed(2)} 秒 · ${result.wave.sample_rate_hz} Hz · ${result.wave.near_silent?'疑似近静音':'波形有效'}`:'当前格式未做波形解码'},
      ]}/>
      <Alert className="settings-model-alert" type="info" showIcon title="这是适配器测量，不是圆屏端到端延迟" description={result.limitations.join('；')}/>
      {!result.history_saved&&<Alert type="warning" showIcon title="测量已完成，但历史没有保存" description="本机测试档案不可用；结果仍是真实本次测量，请不要重复点击。"/>}
    </>}
    <h4>跨启动测试历史</h4>
    <p className="subtle">切换后端并重启后，继续选择同一文本运行；这里只保存固定用例 ID 和指标，不保存音频、聊天或记忆。</p>
    {index.data?.history.state==='unavailable'&&<Alert type="warning" showIcon title="历史档案暂时不可用" description="没有覆盖异常文件；当前测试仍可运行。"/>}
    <Table size="small" pagination={false} rowKey="id" dataSource={(index.data?.history.runs??[]).slice(0,12)}
      locale={{emptyText:'还没有测试记录'}} columns={[
        {title:'后端',dataIndex:'backend',key:'backend'},
        {title:'固定用例',dataIndex:'case_id',key:'case_id',render:(value:string)=>index.data?.cases.find(item=>item.id===value)?.label??value},
        {title:'首个可用音频',dataIndex:'first_audio_available_ms',key:'first',render:(value:number)=>`${value.toFixed(0)} ms`},
        {title:'音频时长',key:'duration',render:(_value,record)=>record.wave?`${record.wave.duration_seconds.toFixed(2)} 秒`:'—'},
        {title:'记录时间',dataIndex:'started_at',key:'time',render:(value:string)=>new Date(value).toLocaleString()},
      ]}/>
  </section>;
}
