import {createContext, useContext, useEffect, useMemo, useRef, type ReactNode} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useLocation} from 'react-router-dom';
import {ApiError, ChatApi} from '../api';

export interface MemoryEngineIdentity {
  schema_version:1;configured:boolean;method:string|null;representation:'atomic_fact'|'method_defined'|null;
  legacy_sqlite:boolean|null;state:'available'|'not_initialized'|'unconfigured';
}
export type MemoryEngineKind='hy'|'legacy'|'other'|'unconfigured'|'uninitialized'|'unknown';
export interface MemoryEngineContextValue {
  phase:'loading'|'ready'|'error';
  kind:MemoryEngineKind;
  identity?:MemoryEngineIdentity;
  issue?:'busy'|'unavailable';
  refreshing:boolean;
  refresh:()=>void;
}
const unknown:MemoryEngineContextValue={phase:'loading',kind:'unknown',refreshing:false,refresh:()=>{}};
export const MemoryEngineContext=createContext<MemoryEngineContextValue>(unknown);
export const useMemoryEngine=()=>useContext(MemoryEngineContext);
const api=new ChatApi();

export function parseMemoryIdentity(value:unknown):MemoryEngineIdentity {
  if(!value||typeof value!=='object')throw new Error('memory_identity_invalid');
  const data=value as MemoryEngineIdentity;
  if(data.schema_version!==1||typeof data.configured!=='boolean'||
    !['available','not_initialized','unconfigured'].includes(data.state)||
    !(data.method===null||typeof data.method==='string')||![null,'atomic_fact','method_defined'].includes(data.representation)||
    !(data.legacy_sqlite===null||typeof data.legacy_sqlite==='boolean')||
    (data.state==='available'&&(!data.configured||!data.method?.trim()||typeof data.legacy_sqlite!=='boolean'||data.representation!==(data.legacy_sqlite?'atomic_fact':'method_defined')))||
    (data.state==='not_initialized'&&(!data.configured||data.method!==null||data.legacy_sqlite!==true||data.representation!=='atomic_fact'))||
    (data.state==='unconfigured'&&(data.configured||data.method!==null||data.representation!==null||data.legacy_sqlite!==null)))throw new Error('memory_identity_invalid');
  return data;
}
function kindOf(identity?:MemoryEngineIdentity):MemoryEngineKind {
  if(!identity)return 'unknown';
  if(identity.state==='unconfigured')return 'unconfigured';
  if(identity.state==='not_initialized')return 'uninitialized';
  if(identity.method==='hy_memory_pro_chat'&&identity.legacy_sqlite===false)return 'hy';
  if(identity.legacy_sqlite===true)return 'legacy';
  return 'other';
}

/** 全站共用轻量身份读取；失败不猜旧引擎，也不让记忆探测阻塞聊天挂载。 */
export function MemoryEngineProvider({children}:{children:ReactNode}) {
  const location=useLocation();
  const previousPath=useRef(location.pathname);
  const query=useQuery({queryKey:['memory-engine-identity'],queryFn:async()=>{
    await api.bootstrap();return parseMemoryIdentity(await api.request<unknown>('/api/memory-engine/identity'));
  },retry:false,staleTime:15000,refetchOnWindowFocus:false});
  useEffect(()=>{
    if(previousPath.current===location.pathname)return;
    previousPath.current=location.pathname;
    if(!query.isError&&!query.isFetching&&Date.now()-query.dataUpdatedAt>15000)void query.refetch();
  },[location.pathname,query.dataUpdatedAt,query.isFetching,query.refetch]);
  const value=useMemo<MemoryEngineContextValue>(()=>({
    phase:query.isError?'error':query.data?'ready':'loading',kind:kindOf(query.data),identity:query.data,
    issue:query.isError&&query.error instanceof ApiError&&query.error.code==='memory_identity_busy'?'busy':query.isError?'unavailable':undefined,
    refreshing:query.isFetching,refresh:()=>{void query.refetch();},
  }),[query.isError,query.error,query.data,query.isFetching,query.refetch]);
  return <MemoryEngineContext.Provider value={value}>{children}</MemoryEngineContext.Provider>;
}

/** 只保留已确认旧引擎的兼容统计；Hy 总览/聊天绝不为计数进入 SDK 或共享锁。 */
export function useMemorySummary(enabled=true) {
  const engine=useMemoryEngine();
  return useQuery({queryKey:['legacy-memory-entry-summary',engine.identity?.method],retry:false,staleTime:30000,
    enabled:enabled&&engine.phase==='ready'&&engine.kind==='legacy',
    queryFn:async()=>{const data=await api.request<{total:number}>('/api/memories?q=&state=active&offset=0&limit=1');if(!Number.isInteger(data.total)||data.total<0)throw new Error('memory_count_invalid');return data;},
  });
}

export function memoryEngineLabel(engine:MemoryEngineContextValue) {
  if(engine.kind==='hy')return engine.phase==='error'?'Hy-Memory（上次确认）':'Hy-Memory';
  if(engine.kind==='legacy')return engine.phase==='error'?'原记忆引擎（上次确认）':'原记忆引擎';
  if(engine.kind==='other')return engine.identity?.method??'独立记忆引擎';
  if(engine.kind==='uninitialized')return '记忆已配置，尚未初始化';
  if(engine.kind==='unconfigured')return '尚未配置记忆引擎';
  return engine.phase==='error'?'记忆引擎读取失败':'正在确认记忆引擎';
}

export function retrievalLabel(retrieval?:string) {
  if(retrieval==='keyword_dense_rrf_v1')return '关键词＋本地向量';
  if(retrieval?.startsWith('hy_'))return 'Hy 分层召回';
  if(retrieval?.startsWith('keyword'))return '关键词基线';
  return retrieval||'尚未提供';
}
