// 可测试的文案与分页规则；不存储记忆、不拼接 HTML。
export function memoryError(code) {
  return ({
    memory_not_configured: "尚未选择记忆库。请用 --database 参数重启控制台，设备控制不受影响。",
    memory_database_missing: "指定数据库不存在。控制台没有创建空库；请检查启动路径。",
    memory_schema_unsupported: "数据库版本不匹配。控制台不会自动升级，请先核对数据库版本。",
    memory_read_only: "当前为只读模式。允许删除需在启动时显式添加 --allow-memory-delete。",
    memory_not_found: "这条记忆已经不存在，请刷新列表。",
    memory_changed: "这条记忆或来源已变化，未执行删除。请重新查看并确认。",
    memory_busy: "数据库正被其他操作占用。请稍后刷新；不要重复点击删除。",
    memory_database_unavailable: "无法读取数据库，请检查文件权限或占用情况。",
    memory_database_invalid: "数据库内容或结构异常，未当作空列表处理。",
    session_required: "网页会话已失效，请刷新整个页面。未自动重发删除操作。",
    csrf_rejected: "请求校验失败，请刷新整个页面。未自动重发删除操作。",
  })[code] || "请求未完成；若刚执行删除，结果可能未知。请刷新核对，不要连续重试。";
}
export function displayTime(value) {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", {hour12: false});
}
export function pageState(total, offset, limit) {
  return {previous: offset > 0, next: offset + limit < total && offset + limit <= 100000,
    label: !total ? "0 条" : offset >= total ? `当前页为空 / 共 ${total} 条` : `${offset + 1}–${Math.min(offset + limit, total)} / ${total}`};
}
export function metadata(memory) {
  return [["记忆 ID", memory.id], ["主体", memory.subject_id], ["状态", memory.state === "retired" ? "已退役" : "未退役"],
    ["系统记录时间", displayTime(memory.recorded_at)], ["事实生效时间", displayTime(memory.valid_from)],
    ["事实结束时间", displayTime(memory.valid_to)], ["退役时间", displayTime(memory.retired_at)], ["被哪条取代", memory.superseded_by_id || "无记录"]];
}
