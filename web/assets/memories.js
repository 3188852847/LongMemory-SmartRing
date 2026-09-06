import {memoryError, displayTime, pageState, metadata} from "./memory-view.mjs";

const el = id => document.getElementById(id);
const state = {csrf: null, config: null, items: [], total: 0, offset: 0, limit: 25,
  query: "", filter: "active", loading: false, writing: false, selected: null, listSeq: 0, detailSeq: 0};

async function api(path, options = {}) {
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
  const headers = options.bootstrap ? {"X-Console-Bootstrap": "1"} : {};
  if (options.body) { headers["Content-Type"] = "application/json"; headers["X-Console-CSRF"] = state.csrf || ""; }
  try {
    const response = await fetch(path, {method: options.method || "GET", headers, credentials: "same-origin",
      redirect: "error", signal: controller.signal, body: options.body ? JSON.stringify(options.body) : undefined});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "request_failed");
    return data;
  } finally { clearTimeout(timeout); }
}
function notice(error) {
  el("memory-notice").classList.toggle("hidden", !error);
  el("memory-notice").textContent = error ? memoryError(error.message) : "";
  if (["session_required", "csrf_rejected"].includes(error?.message)) state.csrf = null;
}
function controls() {
  const available = Boolean(state.csrf && state.config?.configured);
  for (const id of ["memory-refresh", "memory-search-button"]) el(id).disabled = !available || state.loading || state.writing;
  const pages = pageState(state.total, state.offset, state.limit);
  el("memory-previous").disabled = !available || state.loading || !pages.previous || state.writing;
  el("memory-next").disabled = !available || state.loading || !pages.next || state.writing;
  el("memory-delete").disabled = !available || !state.selected || !state.config?.allow_delete || state.writing;
  el("memory-correct").disabled = !available || !state.selected || state.selected.state !== "active" || !state.config?.allow_correction || state.writing;
  el("memory-query").disabled = !available || state.writing;
  el("memory-filter").disabled = !available || state.writing;
}
function clearDetails(message = "选择一条记忆，查看完整内容和原始来源。") {
  state.detailSeq += 1; state.selected = null;
  el("memory-detail").classList.add("hidden");
  el("memory-content").textContent = "";
  el("memory-sources").replaceChildren(); el("memory-metadata").replaceChildren();
  el("memory-detail-state").classList.remove("hidden"); el("memory-detail-state").textContent = message;
  controls();
}
function textNode(tag, text, className) {
  const node = document.createElement(tag); node.textContent = text;
  if (className) node.className = className;
  return node;
}
function renderList() {
  el("memory-list").replaceChildren();
  for (const item of state.items) {
    const row = document.createElement("li"), button = document.createElement("button");
    button.type = "button"; button.className = "memory-row"; button.dataset.memoryId = item.id;
    button.append(textNode("span", item.content + (item.truncated ? "…" : ""), "memory-preview"),
      textNode("span", `${item.state === "retired" ? "已退役" : "未退役"} · ${displayTime(item.recorded_at)}`, "memory-row-meta"));
    button.addEventListener("click", () => { void openMemory(item.id); });
    row.append(button); el("memory-list").append(row);
  }
  el("memory-count").textContent = `${state.total} 条`;
  el("memory-list-state").classList.toggle("hidden", state.items.length > 0);
  el("memory-list-state").textContent = state.total ? "当前页没有记录，请返回上一页。" : "没有符合条件的记忆。可清空搜索或切换显示范围。";
  el("memory-page").textContent = pageState(state.total, state.offset, state.limit).label;
}
async function loadList() {
  if (!state.csrf || !state.config?.configured || state.writing) return;
  const seq = ++state.listSeq;
  clearDetails(); notice(null); state.loading = true;
  el("memory-list").replaceChildren(); el("memory-list-state").classList.remove("hidden");
  el("memory-list-state").textContent = "正在读取记忆…"; controls();
  try {
    const query = new URLSearchParams({q: state.query, state: state.filter, offset: String(state.offset), limit: String(state.limit)});
    const result = await api(`/api/memories?${query}`);
    if (seq !== state.listSeq) return;
    state.items = result.items; state.total = result.total; renderList();
  } catch (error) {
    if (seq !== state.listSeq) return;
    state.items = []; state.total = 0; el("memory-count").textContent = "加载失败"; el("memory-page").textContent = "—";
    el("memory-list-state").textContent = "读取失败，不代表数据库没有记忆。"; notice(error);
  } finally { if (seq === state.listSeq) { state.loading = false; controls(); } }
}
async function openMemory(id) {
  if (state.writing || !state.csrf) return;
  clearDetails("正在读取内容与来源…"); notice(null);
  const seq = state.detailSeq;
  try {
    const data = await api(`/api/memories/${encodeURIComponent(id)}`);
    if (seq !== state.detailSeq) return;
    state.selected = data; el("memory-content").textContent = data.content;
    for (const [key, value] of metadata(data)) el("memory-metadata").append(textNode("dt", key), textNode("dd", value));
    for (const [index, source] of data.sources.entries()) {
      const block = document.createElement("details"); block.className = "source-block"; block.open = index === 0;
      const sourceLabel = source.source_type === "user_stated" ? "用户陈述" : source.source_type === "user_corrected" ? "用户纠正" : source.source_type;
      block.append(textNode("summary", `来源 ${index + 1} · ${sourceLabel}`));
      if (source.message) {
        block.append(textNode("p", source.message.content, "source-content"),
          textNode("p", `原始角色：${source.message.role === "user" ? "用户" : source.message.role === "assistant" ? "助手" : source.message.role} · ${displayTime(source.message.created_at)}`, "hint"));
      } else block.append(textNode("p", "原始来源记录缺失；不能确认当时的原文。", "notice"));
      block.append(textNode("p", `消息 ID：${source.source_message_id}`, "hint"), textNode("p", `关联时间：${displayTime(source.linked_at)}`, "hint"));
      el("memory-sources").append(block);
    }
    if (!data.sources.length) el("memory-sources").append(textNode("p", "没有来源关联，需进一步核查。", "notice"));
    el("memory-detail-state").classList.add("hidden"); el("memory-detail").classList.remove("hidden");
    for (const row of document.querySelectorAll(".memory-row")) row.setAttribute("aria-pressed", String(row.dataset.memoryId === id));
  } catch (error) {
    if (seq !== state.detailSeq) return;
    clearDetails("详情读取失败，请重新选择或刷新列表。"); notice(error);
  } finally { controls(); }
}
el("memory-search").addEventListener("submit", event => {
  event.preventDefault(); state.query = el("memory-query").value.trim(); state.filter = el("memory-filter").value;
  state.offset = 0; void loadList();
});
el("memory-refresh").addEventListener("click", () => { state.offset = 0; void loadList(); });
el("memory-previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); void loadList(); });
el("memory-next").addEventListener("click", () => { state.offset += state.limit; void loadList(); });
el("memory-delete").addEventListener("click", () => {
  if (!state.selected || !state.config?.allow_delete) return;
  el("delete-content").textContent = state.selected.content; el("delete-id").textContent = `记忆 ID：${state.selected.id}`;
  el("delete-understood").checked = false; el("delete-confirm").disabled = true; el("delete-dialog").showModal();
});
el("memory-correct").addEventListener("click", () => {
  if (!state.selected || !state.config?.allow_correction || state.selected.state !== "active") return;
  el("correction-old-content").textContent = state.selected.content;
  el("correction-content").value = "";
  el("correction-understood").checked = false;
  el("correction-confirm").disabled = true;
  el("correction-dialog").showModal();
  el("correction-content").focus();
});
el("correction-cancel").addEventListener("click", () => el("correction-dialog").close());
function correctionReady() {
  el("correction-confirm").disabled = !el("correction-understood").checked || !el("correction-content").value.trim();
}
el("correction-understood").addEventListener("change", correctionReady);
el("correction-content").addEventListener("input", correctionReady);
el("correction-confirm").addEventListener("click", async () => {
  if (!state.selected || !el("correction-understood").checked || state.writing) return;
  const selected = state.selected, correctedContent = el("correction-content").value.trim();
  if (!correctedContent) return;
  state.writing = true; el("correction-dialog").close(); controls();
  try {
    const result = await api(`/api/memories/${encodeURIComponent(selected.id)}/corrections`, {
      method: "POST", body: {revision: selected.revision, corrected_content: correctedContent,
        correction_kind: "error", confirm_correction: true}});
    if (result.corrected !== true) throw new Error("correction_unknown");
    state.writing = false; state.offset = 0; await loadList();
    await openMemory(result.new_memory_id);
    el("memory-notice").classList.remove("hidden");
    el("memory-notice").textContent = "纠正已保存：新事实进入当前记忆，旧事实保留为已取代历史。";
  } catch (error) {
    clearDetails("纠正结果未确认。请刷新列表核对，不自动重试。"); notice(error);
  } finally { state.writing = false; controls(); }
});
el("delete-cancel").addEventListener("click", () => el("delete-dialog").close());
el("delete-understood").addEventListener("change", event => { el("delete-confirm").disabled = !event.target.checked; });
el("delete-confirm").addEventListener("click", async () => {
  if (!state.selected || !el("delete-understood").checked || state.writing) return;
  const selected = state.selected; state.writing = true; el("delete-dialog").close(); controls();
  try {
    const result = await api(`/api/memories/${encodeURIComponent(selected.id)}`, {
      method: "DELETE", body: {revision: selected.revision, confirm_delete: true}});
    if (result.deleted !== true) throw new Error("delete_unknown");
    state.writing = false; state.offset = 0; await loadList();
    clearDetails("已删除该条长期记忆及来源关联，原始对话仍保留。");
  } catch (error) {
    clearDetails("删除结果未确认。请刷新列表核对，不自动重试。"); notice(error);
  } finally { state.writing = false; controls(); }
});
try {
  state.csrf = (await api("/api/session", {bootstrap: true})).csrf; state.config = await api("/api/memory-config");
  el("memory-database").textContent = state.config.database || "未指定；未创建新数据库";
  const modes = [state.config.allow_correction ? "允许纠正" : "", state.config.allow_delete ? "允许删除" : ""].filter(Boolean);
  el("memory-mode").textContent = modes.join("、") || "只读";
  el("memory-mode").dataset.tone = state.config.allow_delete ? "warning" : "good";
  if (state.config.configured) await loadList();
  else { notice(new Error("memory_not_configured")); el("memory-list-state").textContent = "启动时指定已有记忆库后，这里才会显示记忆。"; }
} catch (error) { notice(error); el("memory-list-state").textContent = "无法连接控制台，请检查网页服务并刷新。"; }
finally { controls(); }
