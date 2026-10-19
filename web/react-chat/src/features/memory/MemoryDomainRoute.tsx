import {useEffect, useState, type ReactNode} from 'react';
import {Navigate} from 'react-router-dom';
import {Alert, Button} from 'antd';
import {ChatApi} from '../../api';

/** 旧记忆书签在新引擎中进入对应任务；先核对后端，避免挂载旧页并请求旧库。 */
export function MemoryDomainRoute({legacy,view}:{legacy:ReactNode;view:'profile'|'activity'|'items'}) {
  const [mode,setMode]=useState<'loading'|'legacy'|'engine'|'error'>('loading');
  const [retry,setRetry]=useState(0);
  useEffect(()=>{let current=true;const api=new ChatApi();setMode('loading');void api.bootstrap().then(()=>api.request<{representation?:string}>('/api/memory-config')).then(config=>{if(current)setMode(config.representation==='method_defined'?'engine':'legacy');}).catch(()=>{if(current)setMode('error');});return()=>{current=false;};},[retry]);
  if(mode==='engine')return <Navigate to={`/memories?view=${view}`} replace/>;
  if(mode==='legacy')return legacy;
  if(mode==='error')return <Alert type="error" title="尚未确认当前记忆引擎" description="请重新核对后再打开管理页。" action={<Button onClick={()=>setRetry(v=>v+1)}>重新核对</Button>}/>;
  return <p className="page-loading" role="status">正在核对当前记忆引擎…</p>;
}
