// 纯展示函数：模型回答和研究数据永不作为 HTML 或脚本解释。
export function groupLabel(id) {
  const names = {longmemory_v1: "规则提取", longmemory_llm_extract_v2: "模型提取", dialogue_chunks_v1: "对话分块"};
  const [name, strategy] = id.split("/");
  return `${names[name] ?? name}${strategy ? " + " + ({original_keyword: "关键词", dense_cosine: "向量"}[strategy] ?? strategy) : ""}`;
}
export function statusLabel(status) {return {completed:"完成", failed:"失败", interrupted:"中断 / 未运行", incomplete:"未全部完成", completed_with_errors:"含失败", running:"运行中"}[status] ?? "状态未知";}
export function verdictLabel(value) {return {pass:"通过", fail:"失败", pending:"待判断", unscorable:"不可评分"}[value] ?? "未提供";}
export function evidenceLabel(value) {return value === true ? "充分" : value === false ? "不足" : "不适用 / 未提供";}
export function filterRuns(runs, query, filter) {
  return runs.filter(r => (filter === "all" || (filter === "retrieval" ? r.kind === "retrieval" :
    filter === "fake" ? r.provider === "fake" : r.kind !== "retrieval" && r.provider === "openai_compatible")) &&
    `${r.id} ${r.model} ${r.dataset}`.toLowerCase().includes(query.trim().toLowerCase()));
}
export function node(doc, tag, text, cls) {
  const result = doc.createElement(tag); if (text !== undefined) result.textContent = text;
  if (cls) result.className = cls; return result;
}
export function disclosure(doc, title, content) {
  const block = node(doc, "details", undefined, "evidence-block");
  block.append(node(doc, "summary", title), node(doc, "p", content ?? "未提供", "evidence-text")); return block;
}
export function renderEvidence(doc, row) {
  const root = node(doc, "div");
  root.append(disclosure(doc, "实际注入上下文", row.injected_context === "" ? "空：没有注入记忆" : row.injected_context));
  root.append(disclosure(doc, "完整检索上下文", row.context === "" ? "空：没有召回记忆" : row.context));
  const list = node(doc, "details", undefined, "evidence-block");
  list.append(node(doc, "summary", `召回条目与来源 ID（${row.retrieved.length}）`));
  for (const [index, item] of row.retrieved.entries()) list.append(node(doc, "p", `${index + 1}. ${item.content}\n来源：${item.source_event_ids?.join("、") ?? "未提供"}`, "evidence-text"));
  root.append(list);
  const sources = node(doc, "details", undefined, "evidence-block"); sources.append(node(doc, "summary", "原始来源（含说话角色）"));
  if (!row.sources.length) sources.append(node(doc, "p", "没有可展示的来源。", "hint"));
  for (const source of row.sources) sources.append(node(doc, "p", `${source.event_id} · ${source.role}\n${source.content}`, "evidence-text"));
  root.append(sources); return root;
}
