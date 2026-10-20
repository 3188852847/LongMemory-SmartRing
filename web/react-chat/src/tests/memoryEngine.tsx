import type {ReactNode} from 'react';
import {MemoryEngineContext, type MemoryEngineContextValue, type MemoryEngineIdentity, type MemoryEngineKind} from '../app/MemoryEngineProvider';

export const hyIdentity:MemoryEngineIdentity={schema_version:1,configured:true,method:'hy_memory_pro_chat',representation:'method_defined',legacy_sqlite:false,state:'available'};
export const legacyIdentity:MemoryEngineIdentity={schema_version:1,configured:true,method:'longmemory_daily_llm_v2',representation:'atomic_fact',legacy_sqlite:true,state:'available'};
/** 单独组件的显式已确认身份；全局读协议另用真实 Provider 测试。 */
export function KnownMemoryEngine({children,kind='legacy',value}:{children:ReactNode;kind?:MemoryEngineKind;value?:Partial<MemoryEngineContextValue>}) {
  const identity=kind==='hy'?hyIdentity:kind==='legacy'?legacyIdentity:{...hyIdentity,method:'synthetic_directory'};
  return <MemoryEngineContext.Provider value={{phase:'ready',kind,identity,refreshing:false,refresh:()=>{},...value}}>{children}</MemoryEngineContext.Provider>;
}
