import {statusView, resultView, validTarget, errorMessage} from "./state.mjs";

const byId = id => document.getElementById(id);
const state = {csrf: null, busy: false, polling: false, status: null, readAt: null};
const time = () => new Date().toLocaleTimeString("zh-CN", {hour12: false});

async function request(path, {method = "GET", body, bootstrap = false} = {}) {
  const headers = {};
  if (bootstrap) headers["X-Console-Bootstrap"] = "1";
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["X-Console-CSRF"] = state.csrf || "";
  }
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 21000);
  try {
    const response = await fetch(path, {method, headers, credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body), signal: abort.signal, redirect: "error"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "request_failed");
    return data;
  } finally { clearTimeout(timeout); }
}

function failCode(error) {
  return error.name === "AbortError" ? "request_timeout" : error.message;
}

function invalidateReading(message = "连接已变化，请重新读取设备音量。") {
  state.readAt = null;
  byId("current-volume").textContent = "—";
  byId("volume-freshness").textContent = message;
}

function syncControls() {
  const view = statusView(state.status);
  byId("read-volume").disabled = state.busy || !view.read || !state.csrf;
  byId("volume-controls").disabled = state.busy || !view.set || !state.csrf;
  byId("refresh-status").disabled = state.busy || state.polling || !state.csrf;
  byId("apply-volume").textContent = state.busy ? "正在等待设备…" : "应用音量";
}

function showStatus(data) {
  state.status = data;
  const view = statusView(data);
  const badge = byId("connection-badge");
  badge.textContent = view.badge;
  badge.dataset.tone = view.tone;
  for (const [id, value] of [["bridge-state", view.bridge], ["device-state", view.device], ["tool-state", view.tools], ["connection-help", view.help]]) byId(id).textContent = value;
  byId("updated-at").textContent = `刷新于 ${time()}`;
  if (!view.read) invalidateReading("设备暂不可读；旧读数已清除。");
  if (state.readAt && Date.now() - state.readAt > 30000) invalidateReading("读数已超过 30 秒，请重新读取。");
  syncControls();
}

async function refreshStatus() {
  if (!state.csrf || state.polling || state.busy) return state.status;
  state.polling = true;
  syncControls();
  try { showStatus(await request("/api/device")); }
  catch (error) {
    const code = failCode(error);
    if (code === "session_required") expireSession(code);
    showStatus({error: code});
  } finally { state.polling = false; syncControls(); }
  return state.status;
}

function expireSession(code) {
  state.csrf = null;
  byId("session-notice").classList.remove("hidden");
  byId("session-notice").textContent = errorMessage(code);
}

function showResult(data, action) {
  const view = resultView(data, action);
  byId("operation-result").dataset.tone = view.tone;
  byId("result-title").textContent = view.title;
  byId("result-description").textContent = view.description;
  document.querySelector(".result-symbol").textContent = view.tone === "good" ? "✓" : "!";
  const details = byId("result-details");
  details.replaceChildren();
  // 所有动态字段都按纯文本插入；未来记忆与来源页也沿用此边界。
  for (const [label, value] of [...view.details, ["操作时间", time()]]) {
    const term = document.createElement("dt"), description = document.createElement("dd");
    term.textContent = label;
    description.textContent = String(value);
    details.append(term, description);
  }
  details.classList.remove("hidden");
}

async function operate(action) {
  if (state.busy) return;
  const target = byId("volume-number").valueAsNumber;
  if (action === "set" && !validTarget(target)) { byId("volume-number").reportValidity(); return; }
  state.busy = true;
  invalidateReading("正在向设备读取并核对…");
  syncControls();
  try {
    const data = await request("/api/device/volume", action === "set" ? {method: "POST", body: {volume: target}} : {});
    showResult(data, action);
    const value = action === "read" ? data.volume : data.readback_volume;
    if (Number.isInteger(value)) {
      state.readAt = Date.now();
      byId("current-volume").textContent = String(value);
      byId("volume-freshness").textContent = `最近读取于 ${time()}；不是持续监测。`;
    } else invalidateReading("未取得读回值，请手动读取核对。");
  } catch (error) {
    const code = failCode(error);
    if (["session_required", "csrf_rejected"].includes(code)) expireSession(code);
    showResult({error: code}, action);
    invalidateReading("操作结果未确认，旧读数已清除。");
  } finally { state.busy = false; syncControls(); await refreshStatus(); }
}

byId("volume-slider").addEventListener("input", event => { byId("volume-number").value = event.target.value; });
byId("volume-number").addEventListener("input", event => {
  if (validTarget(event.target.valueAsNumber)) byId("volume-slider").value = event.target.value;
});
byId("volume-form").addEventListener("submit", event => { event.preventDefault(); void operate("set"); });
byId("read-volume").addEventListener("click", () => { void operate("read"); });
byId("refresh-status").addEventListener("click", () => { void refreshStatus(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) void refreshStatus(); });

try {
  state.csrf = (await request("/api/session", {bootstrap: true})).csrf;
  await refreshStatus();
} catch (error) {
  showStatus({error: failCode(error)});
  byId("session-notice").classList.remove("hidden");
  byId("session-notice").textContent = "无法建立控制台会话。请确认本机网页服务仍在运行，再刷新页面。";
}
setInterval(() => { if (!document.hidden) void refreshStatus(); }, 5000);

// 可选浏览器能力：只暴露连接状态查询，不注册远程调音量或绕过按钮的写工具。
// 普通浏览器不支持时静默保持现有网页功能，令牌仍只在 Python 后端。
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  window.addEventListener("pagehide", () => lifecycle.abort(), {once: true});
  try {
    await document.modelContext.registerTool({
      name: "get_device_connection_status", title: "查看圆屏连接状态",
      description: "查询本机小智桥的缓存连接状态并更新页面；不唤醒设备、不读写音量。",
      inputSchema: {type: "object", properties: {}, additionalProperties: false},
      annotations: {readOnlyHint: true, untrustedContentHint: false},
      async execute(input) {
        if (!input || typeof input !== "object" || Array.isArray(input) || Object.keys(input).length) throw new Error("需要空对象参数");
        if (state.busy || state.polling) throw new Error("操作进行中，请稍后查询");
        if (!state.csrf) throw new Error("网页会话不可用，请刷新页面");
        const result = await refreshStatus();
        if (result?.error) return {ok: false, reason: errorMessage(result.error)};
        return {ok: true, ...result};
      },
    }, {signal: lifecycle.signal});
  } catch { /* 不支持或注册失败不影响人工使用，也不声称工具验证通过。 */ }
}
