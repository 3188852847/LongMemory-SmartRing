import {renderTurn} from "/assets/chat-view.mjs";

const $ = id => document.getElementById(id);
let csrf, chatId, pending = false, unknown = false, shown = 0;
let selectionKey;
function rememberSelection() {
  try { localStorage.setItem(selectionKey, chatId); } catch (_) { /* 禁用存储不影响服务端档案。 */ }
}
const errors = {
  chat_busy: "已有消息正在处理，请稍后查询结果。", chat_capacity: "会话档案数量达到当前上限；重启不会清除档案。",
  chat_turn_limit: "本聊天已达 40 轮，请开启新聊天；长期记忆会保留。",
  session_required: "本机会话已失效。请刷新页面；不要自动重发刚才的消息。",
  chat_disabled: "文字聊天未启用。请按部署文档用 --enable-chat 和已有数据库启动。",
};
function notice(message) { $("chat-notice").textContent = message; }
function controls() {
  $("chat-input").disabled = !chatId || pending || unknown || shown >= 40;
  $("chat-send").disabled = $("chat-input").disabled;
  $("new-chat").disabled = !chatId || pending || unknown;
  $("chat-select").disabled = pending || unknown;
  $("rename-chat").disabled = !chatId || pending || unknown;
  $("chat-recover").classList.toggle("hidden", !unknown);
}
async function api(path, method = "GET", body) {
  const headers = method === "GET" ? {} : {"X-Console-CSRF": csrf};
  if (body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method, headers, credentials: "same-origin", cache: "no-store", body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw new Error(errors[data.error] ?? `请求失败（${data.error ?? response.status}），请查询结果，不要盲目重发。`);
  return data;
}
function append(turn) {
  $("chat-turns").append(renderTurn(document, turn));
  shown += 1;
  $("chat-count").textContent = `${shown} / 40 轮`;
  $("chat-empty").classList.add("hidden");
}
async function create() {
  const data = await api("/api/chats", "POST");
  chatId = data.chat_id; shown = 0;
  rememberSelection();
  $("chat-turns").replaceChildren(); $("chat-count").textContent = "0 / 40 轮";
  $("chat-empty").classList.remove("hidden");
  notice("新聊天已就绪。长期记忆保留；发送会保存原始输入，并按现有规则提取记忆。");
  await listChats();
}
async function listChats() {
  const data = await api('/api/chats');
  $("chat-select").replaceChildren();
  for (const chat of data.chats) {
    const option = document.createElement('option');
    option.value = chat.chat_id;
    option.textContent = `${chat.title} · ${chat.turn_count} 轮`;
    $("chat-select").append(option);
  }
  if (chatId) $("chat-select").value = chatId;
  return data.chats;
}
async function loadChat(id) {
  const data = await api(`/api/chats/${id}`);
  chatId = id; shown = 0; unknown = data.pending;
  rememberSelection();
  $("chat-turns").replaceChildren();
  $("chat-empty").classList.toggle('hidden', data.turns.length > 0);
  $("chat-count").textContent = '0 / 40 轮';
  for (const turn of data.turns) append(turn);
  $("chat-select").value = id;
  notice(data.pending ? '此会话正在处理消息，请查询结果，不要重发。' : '会话已恢复；继续聊天只带入最近六轮成功对话。');
  controls();
}
$("chat-select").addEventListener('change', async () => {
  if ($("chat-input").value && !confirm('切换会清空尚未发送的草稿，继续吗？')) {
    $("chat-select").value = chatId; return;
  }
  pending = true; controls();
  try { await loadChat($("chat-select").value); $("chat-input").value = ''; }
  catch (error) { notice(error.message); }
  finally { pending = false; controls(); }
});
$("rename-chat").addEventListener('click', async () => {
  const title = prompt('聊天名称（1–60 字）');
  if (title === null) return;
  pending = true; controls();
  try { await api(`/api/chats/${chatId}/title`, 'POST', {title}); await listChats(); }
  catch (error) { notice(error.message); }
  finally { pending = false; controls(); }
});
$("chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (pending || unknown || !chatId || !$("chat-input").value.trim()) return;
  pending = true; controls(); notice("正在处理：保存输入、提取、检索、调用回答器…请勿重复发送。");
  try {
    const turn = await api(`/api/chats/${chatId}/messages`, "POST", {text: $("chat-input").value, request_id: crypto.randomUUID()});
    append(turn); $("chat-input").value = "";
    notice(turn.status === "completed" ? "本轮完成，可展开查看写入与召回证据。" : "本轮失败。请展开过程查看已完成的阶段；输入可能已保存，不自动重试。");
  } catch (error) {
    unknown = true; notice(`${error.message} 操作结果暂未确认，可点击下方按钮只查询、不重发。`);
  } finally { pending = false; controls(); }
});
$("chat-recover").addEventListener("click", async () => {
  try {
    const data = await api(`/api/chats/${chatId}`);
    if (data.pending) { notice("后台仍在处理，请稍后再次查询；没有重发消息。"); return; }
    const received = data.turns.length > shown;
    for (const turn of data.turns.slice(shown)) append(turn);
    unknown = false;
    if (received) $("chat-input").value = "";
    notice(received ? "已找回处理结果，请展开查看。" : "当前会话没有新增处理记录；请检查输入或重新发送。服务重启后不能据此保证未写入。");
    controls();
  } catch (error) { notice(error.message); }
});
$("new-chat").addEventListener("click", async () => {
  if ($("chat-input").value && !confirm('新建会清空尚未发送的草稿，继续吗？')) return;
  pending = true; controls();
  try { await create(); $("chat-input").value = ''; }
  catch (error) { notice(error.message); }
  finally { pending = false; controls(); }
});
async function start() {
  try {
    const response = await fetch("/api/session", {headers: {"X-Console-Bootstrap": "1"}, cache: "no-store"});
    if (!response.ok) throw new Error("无法建立本机会话。");
    csrf = (await response.json()).csrf;
    const config = await api("/api/chat-config");
    if (!config.enabled) { notice(errors.chat_disabled); return; }
    $("chat-config").textContent = `${config.method} · ${config.subject} · ${config.model} · ${config.role}${config.provider === "fake" ? "（离线替身，不具备角色和多轮理解能力）" : ""}`;
    $("chat-database").textContent = `记忆库：${config.database}。网页和小智的配置需指向同一文件，角色/模型请核对各自启动配置。`;
    const chats = await listChats();
    selectionKey = `longmemory:last-chat:${config.database}`;
    let previous;
    try { previous = localStorage.getItem(selectionKey); } catch (_) { /* 默认最近创建的聊天。 */ }
    if (chats.length) await loadChat(chats.find(c => c.chat_id === previous)?.chat_id ?? chats[0].chat_id);
    else await create();
    controls();
  } catch (error) { notice(error.message); }
}
start();
