import {ChatApi} from './client';
import {parseHyMechanisms} from './hyMechanisms';
import type {EngineItem, EnginePage, EngineSource, EngineStatus, HyWorkspace, HyHistory, HyOperation, HyMutationResult} from './types/memory';

/** 所有动作共享会话/CSRF，无隐式重试、旧库回落或 HTTP 路径配置。 */
export class MemoryEngineApi {
  constructor(private api:ChatApi) {}
  status() {return this.api.request<EngineStatus>('/api/memory-engine');}
  items(offset=0) {return this.api.request<EnginePage<EngineItem>>(`/api/memory-engine/items?limit=25&offset=${offset}`);}
  item(id:string) {return this.api.request<EngineItem>(`/api/memory-engine/items/${encodeURIComponent(id)}`);}
  source(id:string) {return this.api.request<EngineSource>(`/api/memory-engine/sources/${encodeURIComponent(id)}`);}
  workspace() {return this.api.request<HyWorkspace>('/api/memory-engine/hy/workspace');}
  async mechanisms() {return parseHyMechanisms(await this.api.request<unknown>('/api/memory-engine/hy/mechanisms'));}
  profile() {return this.api.request<{item:EngineItem|null}>('/api/memory-engine/hy/profile');}
  history(id:string) {return this.api.request<HyHistory>(`/api/memory-engine/hy/items/${encodeURIComponent(id)}/history`);}
  operations(offset=0,itemId?:string) {const params=new URLSearchParams({limit:'25',offset:String(offset)});if(itemId)params.set('item_id',itemId);return this.api.request<EnginePage<HyOperation>>(`/api/memory-engine/hy/operations?${params}`);}
  correct(id:string,revision:string,content:string,requestId:string) {return this.api.request<HyMutationResult>(`/api/memory-engine/hy/items/${encodeURIComponent(id)}/corrections`,'POST',{revision,content,request_id:requestId});}
  delete(id:string,revision:string,requestId:string) {return this.api.request<HyMutationResult>(`/api/memory-engine/hy/items/${encodeURIComponent(id)}/deletion`,'POST',{revision,request_id:requestId,confirmation:'删除这条记忆'});}
}
