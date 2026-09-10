// 纯状态映射可在 Node 中独立测试；不接触 DOM、令牌或真实圆屏。
export function validTarget(value) {
  return Number.isInteger(value) && value >= 5 && value <= 60;
}

export function statusView(data) {
  if (!data || data.error) return {
    tone: "error", badge: "控制服务不可用", bridge: "未连接", device: "未知", tools: "未知",
    read: false, set: false, help: errorMessage(data?.error),
  };
  const read = data.ready === true && data.read_volume_supported === true;
  const set = read && data.set_volume_supported === true;
  if (data.connection_count === 0) return {
    tone: "warning", badge: "请唤醒圆屏", bridge: "已连接", device: "当前无活动连接",
    tools: "等待连接", read: false, set: false,
    help: "小智服务可达。请轻触圆屏进入聆听状态，等待下一次刷新。",
  };
  if (data.connection_count !== 1) return {
    tone: "warning", badge: "连接状态异常", bridge: "已连接", device: "存在重复连接",
    tools: "暂不可用", read: false, set: false, help: "同一设备存在多条连接，暂不允许控制。",
  };
  const screenTools = [data.set_brightness_supported, data.set_theme_supported].filter(Boolean).length;
  return {tone: set ? "good" : "warning", badge: set ? "可以控制" : "工具尚未就绪",
    bridge: "已连接", device: "1 台已连接", tools: set ? `音量可用 · 屏幕 ${screenTools}/2` : read ? "仅可读取" : "等待工具握手",
    read, set, help: set ? "已识别设备工具；写入后会等待回执并尽量核对读回值。" : "设备已连接，控制工具还不可用。请稍候；持续异常时查看小智服务日志。"};
}

export function errorMessage(code) {
  const messages = {
    bridge_not_configured: "未找到控制令牌。请先用 --device-control 启动小智服务。",
    bridge_unavailable: "无法连接本机小智控制服务。请检查小智是否仍在运行，并已启用 --device-control。",
    bridge_auth_failed: "控制服务拒绝鉴权，请核对小智与控制台是否使用同一项目。",
    session_required: "网页会话已失效，请刷新整个页面。未自动重发指令。",
    csrf_rejected: "请求校验失败，请刷新整个页面。未自动重发指令。",
    origin_rejected: "访问来源不符合本机限制，请使用 127.0.0.1 地址打开。",
    device_offline: "圆屏当前不在线，请唤醒后重新读取。",
    device_not_ready: "圆屏连接尚未就绪，请稍候重新读取。",
    tools_not_ready: "音量工具握手尚未完成，请稍候。",
    control_busy: "另一个控制操作正在执行，请等待完成后再读取。",
    stop_speech_unavailable: "当前小智连接没有可用的语音中止通道。",
    operation_busy: "另一个控制操作正在执行，请等待完成后再读取。",
    invalid_volume: "目标音量必须是 5–60 之间的整数。",
    readback_mismatch: "设备读回值与目标不一致，不能确认设置成功。",
  };
  return messages[code] || "未能确认操作结果，音量可能已改变。请先读取核对，不要连续重试。";
}

export function resultView(data, action) {
  if (data?.error) return {tone: "error", title: "未能确认操作结果", description: errorMessage(data.error), details: []};
  if (action === "read" && Number.isInteger(data?.volume) && data.volume >= 0 && data.volume <= 100)
    return {tone: "good", title: "已读取设备音量", description: "这是设备本次返回的值，不代表电量或实时持续监测。", details: [["读取值", data.volume]]};
  if (action === "set" && data?.acknowledged === true) {
    if (Object.hasOwn(data, "requested_value")) {
      const verified = data.verified === true && data.readback_value === data.requested_value;
      return {tone: verified ? "good" : "warning", title: verified ? "屏幕设置已核对" : "收到回执，尚未核对成功",
        description: verified ? "设备执行后返回值与目标一致。" : "不要立即重试；请读取设备快照核对实际状态。",
        details: [["设置前", data.previous_value ?? "未取得"], ["目标值", data.requested_value], ["设备回执", "已确认"], ["读回值", data.readback_value ?? "未取得"]]};
    }
    const verified = data.verified === true && validTarget(data.requested_volume) && data.readback_volume === data.requested_volume;
    return {tone: verified ? "good" : "warning", title: verified ? "音量已核对" : "收到回执，尚未核对成功",
      description: verified ? "设备已确认执行，随后读回的音量与目标一致。" : "不要立即重试设置。请读取当前值，确认设备实际状态。",
      details: [["设置前", data.previous_volume], ["目标值", data.requested_volume], ["设备回执", "已确认"], ["读回值", data.readback_volume ?? "未取得"]]};
  }
  return resultView({error: "invalid_response"}, action);
}
