import {useState} from 'react';
import {Alert,Button} from 'antd';
import {ApiError} from '../../api';
import {hySemanticTaskPathIdentifier,HySemanticContractError,type HySemanticTask} from '../../api/hySemantic';
import {memoryTime} from './HyMemoryWorkspace';

export const semanticTaskStates={pending:'等待认领',running:'已认领，运行中',completed:'任务已完成',partial:'部分完成',uncertain:'结果不确定',cancelled:'已取消启动'};
export function semanticReadFailure(error:unknown){
  if(error instanceof HySemanticContractError)return error.message;
  if(error instanceof ApiError){
    if(error.code==='hy_semantic_busy')return '引擎忙，本次没有取得新证据；稍后手动重试。';
    if(error.status===501)return '当前服务不支持语义运行读取，能力保持未知。';
    if(error.status===404)return '该任务不存在或不在可读范围，没有从其他范围补读。';
    if(error.status===401)return '本机会话不可用，重新连接后再核对。';
  }
  return '本次读取失败，不表示任务失败、没有任务或语义能力已关闭。';
}

/** 输入已知任务ID后单条GET；没有扫描、提交、取消或重试任务入口。 */
export function HySemanticTaskView({id,task,loading=false,error,disabled=false,onRead}:{id:string;task?:HySemanticTask;loading?:boolean;error?:unknown;disabled?:boolean;onRead:(id:string)=>void}) {
  const [draft,setDraft]=useState(id);
  return <section className="hy-semantic-task" aria-label="单任务只读回执">
    <h3>核对已知任务</h3><form onSubmit={event=>{event.preventDefault();if(hySemanticTaskPathIdentifier(draft)&&!disabled&&!loading)onRead(draft);}}>
      <label>任务 ID<input aria-label="语义任务 ID" value={draft} maxLength={512} onChange={event=>setDraft(event.target.value)}/></label>
      <Button aria-label="读取任务" htmlType="submit" loading={loading} disabled={disabled||!hySemanticTaskPathIdentifier(draft)}>读取任务</Button>
    </form>
    {Boolean(error)&&<Alert type="warning" title={task?'未取得新任务回执，以下保留上次快照':'任务回执未读取'} description={semanticReadFailure(error)}/>}
    {task&&<><p>{loading||error?'上次':'本次'}任务快照：<code>{task.task_id}</code></p><dl>
      <div><dt>任务种类</dt><dd>{task.kind==='evolve'?'图式归纳':'意图过期维护'}</dd></div>
      <div><dt>任务状态</dt><dd>{semanticTaskStates[task.state]}</dd></div>
      <div><dt>创建</dt><dd>{memoryTime(task.created_at)}</dd></div><div><dt>完成</dt><dd>{memoryTime(task.finished_at)}</dd></div>
      <div><dt>任务耗时</dt><dd>{task.elapsed_ms===null?'未提供':`${task.elapsed_ms} ms`}</dd></div><div><dt>原因代码</dt><dd>{task.reason_code??'未返回原因代码'}</dd></div>
      <div><dt>读取</dt><dd>{memoryTime(task.observed_at)}</dd></div></dl>
      {(task.state==='partial'||task.state==='uncertain')&&<p>本状态不会自动重试；不能把不确定结果改写为成功或失败。</p>}
    </>}
    <p>任务完成不代表未来意图已执行、用户事实已确认或回答已播放；本页不会重放任务。</p>
  </section>;
}
