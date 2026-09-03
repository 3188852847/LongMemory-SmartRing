import {groupLabel, statusLabel, verdictLabel, evidenceLabel, filterRuns, node, disclosure, renderEvidence} from "/assets/experiment-view.mjs";
import {initExperimentJobs} from "/assets/experiment-jobs.mjs";
const $ = id => document.getElementById(id), el = (tag, text, cls) => node(document, tag, text, cls);
let csrf, runs = [], page = 0, selected, detail, generation = 0, busy = false, activeQuestion, activeReviewer = "我";
const dirty = new Set();
const errors = {session_required:"本机会话已失效，请刷新页面。", review_changed:"此署名的复核已变化，请重新选择实验后再修改。", report_changed:"原报告已变化，请刷新档案；旧复核不会覆盖新报告。", experiment_unreadable:"报告或复核格式无效，未显示为通过。", review_limit:"复核版本数量达到本页上限。", csrf_rejected:"安全校验失败，请刷新页面。"};
function notice(text) {$('notice').textContent = text;}
Object.assign(errors, {experiment_busy:'已有实验正在运行，请刷新任务查看。', experiment_runs_disabled:'当前控制台未启用实验运行。', model_not_configured:'服务启动时没有有效模型配置。', quote_expired:'预检已过期或会话已变化，请重新预检。', report_changed:'冻结来源已变化，未启动新实验。', source_not_unique:'找不到唯一匹配的原方法实验，请检查档案。', job_input_or_storage_invalid:'实验来源或任务存储校验失败，未自动重试。', network_confirmation_required:'必须明确接受模型调用与 HTTP 风险。', job_not_owned_or_finished:'任务已结束或由另一个控制台运行，请到启动它的控制台停止。'});
async function api(path, method="GET", body) {
  const headers = method === "GET" ? {} : {"X-Console-CSRF":csrf, "Content-Type":"application/json"};
  const response = await fetch(path, {method, headers, credentials:"same-origin", cache:"no-store", body:body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(errors[data.error] ?? `请求未完成：${data.error ?? response.status}`);
  return data;
}
function mayLeave() {return !busy && (!dirty.size || confirm("有未保存的复核，离开会丢弃这些编辑。是否继续？"));}
function dateText(text) {const date = new Date(text); return Number.isNaN(date.getTime()) ? "时间未提供" : date.toLocaleString();}
function renderList() {
  const filtered = filterRuns(runs, $('run-search').value, $('run-filter').value);
  page = Math.min(page, Math.max(0, Math.ceil(filtered.length / 10) - 1));
  $('run-list').replaceChildren();
  for (const run of filtered.slice(page * 10, page * 10 + 10)) {
    const button = el("button", undefined, "memory-row"); button.setAttribute("aria-pressed", String(run.id === selected));
    const type = run.kind === "retrieval" ? "仅检索" : run.provider === "fake" ? "Fake · 工程验证" : run.provider === "openai_compatible" ? "真实模型回答" : "模型类型未确认";
    button.append(el("strong", type), el("span", dateText(run.started_at), "memory-row-meta"), el("span", run.model ?? "模型未提供", "memory-preview"), el("span", `${run.dataset} · ${run.split}\n${statusLabel(run.status)} ${run.completed}/${run.total}`, "memory-row-meta"), el("span", run.id.slice(-8), "memory-row-meta"));
    button.addEventListener("click", () => {if (mayLeave()) openRun(run.id);}); $('run-list').append(button);
  }
  if (!filtered.length) $('run-list').append(el("p", "没有匹配的实验。", "empty-state"));
  $('page-count').textContent = `${filtered.length} 条 · ${filtered.length ? page+1 : 0} / ${Math.ceil(filtered.length/10)}`;
  $('previous').disabled = page === 0; $('next').disabled = (page+1)*10 >= filtered.length;
}
function renderSummary() {
  const table = el("table"), header = el("tr");
  for (const text of ["实验组", "完成 / 总题", "词面初筛 / 总题", "充分证据 / 可评题"]) header.append(el("th", text));
  const thead = el("thead"); thead.append(header); table.append(thead);
  const tbody = el("tbody");
  for (const group of detail.groups) {
    const row = el("tr");
    for (const text of [groupLabel(group.id), `${group.completed}/${group.total}`, group.answer_scored ? `${group.answer_pass}/${group.total}` : "未评分", group.evidence_scored ? `${group.evidence_pass}/${group.evidence_scored}` : "不适用 / 未评分"]) row.append(el("td", text));
    tbody.append(row);
  }
  table.append(tbody); $('group-summary').replaceChildren(table); $('review-summary').replaceChildren();
  for (const review of detail.reviews) {
    const text = Object.entries(review.summary).map(([group, count]) => `${groupLabel(group)} ${count.pass}/${count.total}（待判断 ${count.pending}，不可评分 ${count.unscorable}）`).join("；");
    $('review-summary').append(el("p", `${review.reviewer_kind === "human" ? "人工复核" : "助手复核"} · ${review.reviewer}：${text}`, "hint"));
  }
}
async function openRun(id) {
  dirty.clear(); const ticket = ++generation; selected = id; detail = null;
  $('detail').classList.add("hidden"); $('empty').classList.remove("hidden"); $('empty').textContent="正在读取实验…"; renderList();
  try {
    const result = await api(`/api/experiments/${id}`); if (ticket !== generation) return;
    detail = result; $('empty').classList.add("hidden"); $('detail').classList.remove("hidden");
    $('run-title').textContent = detail.kind === "retrieval" ? "冻结检索对照" : "逐题回答对照";
    $('run-meta').textContent = `${dateText(detail.started_at)} · ${detail.dataset?.name ?? "未知数据集"} · ${detail.split} · ${statusLabel(detail.status)}`;
    $('run-warning').textContent = `${runs.find(r=>r.id===id)?.provider === "fake" ? "Fake 仅验证工程，不用于质量结论。" : "合成开发实验不代表论文基准或总体准确率。"} ${detail.ignored_reviews ? `有 ${detail.ignored_reviews} 份过期或无效附页未计分。` : ""}`;
    $('run-hash').textContent = `报告 ${id}\nSHA256 ${detail.report_sha256}\n代码 ${detail.code_commit ?? "未记录"}${detail.code_dirty ? "（运行时工作区非干净）" : ""}`;
    renderSummary(); $('question-select').replaceChildren();
    for (const q of detail.questions) {const option=el("option",q.query);option.value=q.id;$('question-select').append(option);}
    notice("原报告只读。逐题展开证据；人工复核会另存版本，不改变自动初筛。");
    await openQuestion();
  } catch (error) {if(ticket === generation){$('empty').textContent=error.message;notice(error.message);}}
}
async function openQuestion() {
  dirty.clear(); const ticket=++generation, run=selected, qid=$('question-select').value;
  activeQuestion=qid; activeReviewer=$('reviewer').value;
  $('question-grid').replaceChildren(el("p","正在读取逐题证据…","panel"));
  try {
    const data = await api(`/api/experiments/${run}/question?id=${encodeURIComponent(qid)}`);
    if(ticket !== generation) return;
    if(data.report_sha256 !== detail.report_sha256) throw new Error("报告已变化，请刷新档案。");
    $('source-note').textContent=data.source_note; $('question-grid').replaceChildren();
    for (const row of data.rows) $('question-grid').append(renderQuestion(row,qid));
  } catch(error) {if(ticket===generation){$('question-grid').replaceChildren(el("p",error.message,"panel"));notice(error.message);}}
}
function renderQuestion(row,qid) {
  const card=el("article",undefined,"panel question-card"); card.append(el("h3",groupLabel(row.group)),el("p",statusLabel(row.status),"badge"));
  card.append(el("p",row.answer ?? (detail.kind === "retrieval" ? "此实验只检索，没有生成回答。" : "没有可用回答。"),"answer-text"));
  card.append(el("p",`初筛：${row.answer_proxy_pass === null ? "未评分" : row.answer_proxy_pass ? "通过" : "未通过"} · 证据：${evidenceLabel(row.evidence_complete)}`,"hint"));
  card.append(el("p",`冻结状态：${row.state_unchanged===true ? "运行时报告未变" : row.state_unchanged===false ? "发生变化" : "未提供"}${row.error ? " · " + row.error : ""}`,"hint"));
  card.append(renderEvidence(document,row));
  card.append(disclosure(document,"评分参照（不曾发送给模型）", row.expected_abstention === true ? "期望承认信息不足，不虚构用户事实。" : row.reference_answer ?? "本报告未记录答案参照。"));
  for (const review of detail.reviews) {
    const item=review.items.find(i=>i.method===row.group&&i.question_id===qid);
    if(item) card.append(disclosure(document,`${review.reviewer_kind === "human" ? "人工" : "助手"} · ${review.reviewer} · ${verdictLabel(item.verdict)}`,item.rationale || "尚未填写理由"));
  }
  if(detail.review_enabled) {
    const form=el("form",undefined,"review-form"), key=row.group+qid, select=el("select"), reason=el("textarea"), message=el("p",undefined,"hint");
    const old=detail.reviews.find(r=>r.reviewer_kind==="human"&&r.reviewer===$('reviewer').value)?.items.find(i=>i.method===row.group&&i.question_id===qid);
    for(const value of ["pending","pass","fail","unscorable"]){const option=el("option",verdictLabel(value));option.value=value;select.append(option);}
    select.value=old?.verdict??"pending";reason.value=old?.rationale??"";reason.maxLength=1000;reason.rows=3;reason.placeholder="依据哪些来源或回答作出判断？";
    const label=el("label","我的判断");label.append(select);const reasonLabel=el("label","判断理由（非待判断时必填）");reasonLabel.append(reason);
    const submit=el("button","保存此题复核","button secondary");submit.type="submit";
    form.append(label,reasonLabel,submit,message);card.append(form);
    form.addEventListener("input",()=>dirty.add(key));
    form.addEventListener("submit",async event=>{
      event.preventDefault();if(busy)return;
      const reviewer=$('reviewer').value.trim();if(!reviewer||(!reason.value.trim()&&select.value!=="pending")){message.textContent="请填写署名与判断理由。";return;}
      busy=true;document.querySelectorAll('.review-form button').forEach(b=>b.disabled=true);$('reviewer').disabled=true;$('question-select').disabled=true;
      const run=selected, current=detail.reviews.find(r=>r.reviewer_kind==="human"&&r.reviewer===reviewer);
      try {
        await api(`/api/experiments/${run}/reviews`,"POST",{report_sha256:detail.report_sha256,reviewer,revision:current?.revision??null,method:row.group,question_id:qid,verdict:select.value,rationale:reason.value,request_id:crypto.randomUUID()});
        dirty.delete(key);message.textContent="已保存为新的人工复核版本。原报告与助手复核未改。";
        detail=await api(`/api/experiments/${run}`);renderSummary();
      } catch(error) {message.textContent=error.message+" 若连接中断，结果可能已保存；先刷新档案查看，不自动重发。";}
      finally {busy=false;document.querySelectorAll('.review-form button').forEach(b=>b.disabled=false);$('reviewer').disabled=false;$('question-select').disabled=false;}
    });
  }
  return card;
}
async function refresh() {
  if(!mayLeave())return;dirty.clear();generation++;
  try {const data=await api('/api/experiments');runs=data.items;renderList();notice(`${runs.length} 条实验档案。${data.skipped ? ` ${data.skipped} 条无法读取，未计为通过。` : ""}${data.limited ? " 超过 500 条，仅展示限定范围。" : ""}`);if(selected&&runs.some(r=>r.id===selected))await openRun(selected);else if(runs.length)await openRun((runs.find(r=>r.kind==='answers'&&r.provider==='openai_compatible')??runs[0]).id);else{$('detail').classList.add('hidden');$('empty').classList.remove('hidden');$('empty').textContent='尚无支持的实验报告。已有日常记忆不会自动变成实验。';}}
  catch(error){notice(error.message);}
}
$('refresh').addEventListener('click',refresh);
$('question-select').addEventListener('change',()=>{if(mayLeave())openQuestion();else $('question-select').value=activeQuestion;});
$('reviewer').addEventListener('change',()=>{if(mayLeave())openQuestion();else $('reviewer').value=activeReviewer;});
for(const id of ['run-search','run-filter'])$(id).addEventListener('input',()=>{page=0;renderList();});
$('previous').addEventListener('click',()=>{page--;renderList();});$('next').addEventListener('click',()=>{page++;renderList();});
window.addEventListener('beforeunload',event=>{if(dirty.size||busy){event.preventDefault();event.returnValue='';}});
try {const response=await fetch('/api/session',{headers:{'X-Console-Bootstrap':'1'},credentials:'same-origin',cache:'no-store'});if(!response.ok)throw new Error('本机会话建立失败，请刷新页面。');csrf=(await response.json()).csrf;await refresh();await initExperimentJobs(api,async id=>{if(!mayLeave())return;dirty.clear();selected=id;await refresh();});}catch(error){notice(error.message);}
