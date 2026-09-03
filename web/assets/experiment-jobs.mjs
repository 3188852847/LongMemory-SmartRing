import {groupLabel} from "./experiment-view.mjs";

export function jobStatus(value) {
  return ({queued:"已排定", running:"正在运行", stopping:"正在停止后续请求", completed:"运行完成", incomplete:"部分完成", failed:"运行失败", interrupted:"服务中断，未自动续跑"})[value] ?? "状态未知";
}
export function progressText(job) {
  return `已尝试 ${job.attempts}/${job.total} 次 · 成功 ${job.completed} · 失败 ${job.failed} · 未结束 ${Math.max(0,job.total-job.completed-job.failed)}。尝试次数包含失败调用，不代表正确回答数。`;
}
export function quoteText(quote) {
  return `${quote.model.model} · ${quote.groups.length} 组 × ${quote.question_count} 题 · 最多 ${quote.total} 次回答请求 · 记忆上限 ${quote.context_chars} 字符。单次回答上限 ${quote.model.max_tokens} token，超时 ${quote.model.timeout_seconds} 秒。新增提取 0 次、编码 0 次。${quote.endpoint_host ? '目标服务：'+quote.endpoint_host+'。' : ''}`;
}

// 作业与复核草稿分别管理状态；轮询只 GET，不会重放启动请求。
export async function initExperimentJobs(api, onOpen) {
  const $ = id => document.getElementById(id);
  let quote=null, requestId=null, current=null, timer=null, submitting=false, enabled=false, preparing=false, polling=false;
  const active = job => job && ["queued","running","stopping"].includes(job.status);
  const message = text => {$('job-notice').textContent=text;};
  function controls() {
    for(const id of ['job-source','job-provider','job-budget'])$(id).disabled=preparing||submitting||Boolean(active(current));
    $('job-prepare').disabled=!enabled||active(current)||submitting||preparing||!$('job-source').value;
    $('job-start').disabled=submitting||!quote||!$('job-consent').checked;
    $('job-cancel').disabled=submitting;
    $('job-stop').disabled=!active(current)||current?.status==='stopping';
    $('job-result').disabled=!current?.report_id||active(current);
  }
  async function poll() {
    clearTimeout(timer);if(polling)return;polling=true;
    try {
      const data=await api('/api/experiment-jobs');current=data.items[0]??null;
      $('job-current').classList.toggle('hidden',!current);
      if(current){
        $('job-title').textContent=`${jobStatus(current.status)} · ${current.model.model} · ${current.id.slice(-8)}`;
        $('job-progress').max=current.total;$('job-progress').value=current.completed+current.failed;
        $('job-progress-text').textContent=progressText(current)+(current.error ? ` 状态说明：${current.error}；不会自动重试。` : '');
      }
      controls();
    }catch(error){message(error.message+' 任务可能仍在运行；请刷新任务查看，不要重新启动。');}
    finally {polling=false;if(active(current)&&!document.hidden)timer=setTimeout(poll,2000);}
  }
  try {
    const options=await api('/api/experiment-jobs/options');enabled=options.enabled;
    $('job-source').replaceChildren();
    for(const run of options.retrievals){const option=document.createElement('option');option.value=run.id;option.textContent=`${run.id.slice(-8)} · ${run.dataset} · ${run.started_at}`;$('job-source').append(option);}
    const real=$('job-provider').options[1];real.disabled=!options.real_available;
    real.textContent=options.real_available ? `${options.real_model}（真实模型）` : '兼容模型（未配置）';
    message(!enabled ? '当前服务仅查看档案。需用 --enable-experiment-runs 启动才可运行。' : !options.retrievals.length ? '尚无已完成的开发集冻结检索档案。' : '先核对预算，再确认启动。关闭或刷新网页不会取消已启动任务。');
    await poll();
  }catch(error){message(error.message);}
  $('job-form').addEventListener('submit',async event=>{
    event.preventDefault();if(preparing||submitting||!enabled||active(current))return;
    preparing=true;quote=null;controls();message('正在本机校验来源与预算，不调用模型…');
    try {
      quote=await api('/api/experiment-jobs/prepare','POST',{retrieval_id:$('job-source').value,provider:$('job-provider').value,context_chars:Number($('job-budget').value)});
      requestId=crypto.randomUUID();$('job-consent').checked=false;
      $('job-quote-summary').textContent=quoteText(quote);$('job-quote-groups').textContent=`输入档案：${quote.retrieval_id}。`+quote.groups.map(groupLabel).join('；');
      $('job-quote-risk').textContent=!quote.network ? 'Fake 不联网，仅验证工程流程，不能评价记忆质量。' : quote.insecure_http ? '将通过明文 HTTP 发送凭据、合成问题和记忆。仅在已确认风险的校园网运行；请确保电脑现在能连接模型。' : '将向配置的模型服务发送凭据、合成问题和记忆，可能产生费用。';
      $('job-confirm-error').textContent='';$('job-confirm').showModal();message('预检完成；尚未启动。预算确认在 10 分钟后失效。');
    }catch(error){message(error.message);}
    finally{preparing=false;controls();}
  });
  $('job-consent').addEventListener('change',controls);
  $('job-cancel').addEventListener('click',()=>{quote=null;$('job-confirm').close();controls();});
  $('job-confirm').addEventListener('cancel',event=>{if(submitting)event.preventDefault();else quote=null;});
  $('job-start').addEventListener('click',async()=>{
    if(submitting||!quote||!$('job-consent').checked)return;
    submitting=true;controls();
    try{
      current=await api('/api/experiment-jobs/start','POST',{quote_id:quote.quote_id,request_id:requestId,confirm:true,allow_network:quote.network,allow_http:quote.insecure_http});
      $('job-confirm').close();quote=null;message('已启动。进度自动刷新；可继续查看其他实验或复核。');await poll();
    }catch(error){$('job-confirm-error').textContent=error.message+' 若响应丢失，先刷新任务；再次点确认仍使用同一请求编号，不重复执行。';await poll();}
    finally{submitting=false;controls();}
  });
  $('job-poll').addEventListener('click',poll);
  $('job-stop').addEventListener('click',async()=>{
    if(!active(current)||!confirm('停止尚未开始的题目？已发出的一次请求可能完成或计费，结果会保留。'))return;
    try{await api(`/api/experiment-jobs/${current.id}/stop`,'POST',{});message('已请求停止后续题目。等待当前请求结束，不会自动续跑。');await poll();}catch(error){message(error.message);}
  });
  $('job-result').addEventListener('click',()=>{if(current?.report_id&&!active(current))onOpen(current.report_id);});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else poll();});
  window.addEventListener('pagehide',()=>clearTimeout(timer));
}
