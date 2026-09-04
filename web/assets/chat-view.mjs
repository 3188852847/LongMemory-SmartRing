// 不使用 HTML/Markdown 插值：用户话语、模型回答和记忆证据均是不可信文本。
export function turnSummary(turn) {
  if (turn.status === 'interrupted') return '服务中断 · 写入状态未知，不自动重发；请检查记忆和来源';
  const writes = turn.writes;
  const writeText = writes === null ? "写入结果未提供" :
    `新增 ${writes.filter(x => x.operation === "add").length} 条，复用 ${writes.filter(x => x.operation === "noop").length} 条`;
  return `${turn.status === "completed" ? "完成" : "失败"} · ${writeText} · 用户输入${turn.user_saved ? "已保存" : "未确认保存"} · ${turn.duration_ms} ms`;
}

export function renderTurn(document, turn) {
  const article = document.createElement("article");
  article.className = "chat-turn";
  for (const [label, content] of [["你", turn.input], ["助手", turn.answer ?? "未获得完整回答。"]]) {
    const heading = document.createElement("h3"); heading.textContent = label;
    const paragraph = document.createElement("p"); paragraph.className = "chat-text"; paragraph.textContent = content;
    article.append(heading, paragraph);
  }
  const details = document.createElement("details");
  const summary = document.createElement("summary"); summary.textContent = turnSummary(turn);
  const trace = document.createElement("pre");
  trace.textContent = JSON.stringify({status: turn.status, error: turn.error,
    event_id: turn.event_id, call_id: turn.call_id, started_at: turn.started_at,
    method: turn.method, model: turn.model, role: turn.role,
    assistant_saved: turn.assistant_saved, history_messages: turn.history_messages,
    writes: turn.writes, retrieved: turn.retrieved, memory_context: turn.memory_context}, null, 2);
  details.append(summary, trace);
  article.append(details);
  return article;
}
