/** 把服务端固定诊断码翻译为可行动提示；不展示远程响应正文。 */
export const modelFailureText:Record<string,string> = {
  model_authentication_failed:'模型鉴权失败：Key 可能失效、尚未更新，或当前账号无权访问新部署。',
  model_deployment_not_found:'模型部署地址不存在：学校可能更换了接口路径或下线了原部署。',
  model_unreachable:'无法连接模型服务：请检查校园网、服务地址和服务器是否在线。',
  model_request_timeout:'模型服务响应超时：可能正在重启、负载过高或网络不稳定。',
  model_rate_limited:'模型服务拒绝了过多请求：请稍后再试，不要连续重发。',
  model_service_unavailable:'模型服务端暂不可用：可能正在重启或重新部署。',
  model_response_invalid:'模型接口有响应，但格式不再兼容；部署协议可能发生变化。',
  model_response_truncated:'模型回答达到长度上限，没有作为完整回答保存。',
  model_response_too_large:'模型返回内容超过安全大小限制。',
  model_request_rejected:'模型请求被拒绝，请检查模型名称、接口配置和服务权限。',
  model_request_failed:'模型调用失败，当前信息不足以进一步分类。',
};

export function modelFailure(code:unknown){
  return typeof code==='string' ? modelFailureText[code] : undefined;
}
