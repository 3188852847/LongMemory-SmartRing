import {describe, expect, test} from 'vitest';
import {modelFailure} from './modelHealth';

describe('模型状态安全提示',()=>{
  test.each([
    ['model_authentication_failed','Key'],
    ['model_deployment_not_found','部署地址'],
    ['model_unreachable','校园网'],
    ['model_request_timeout','超时'],
    ['model_rate_limited','过多请求'],
    ['model_service_unavailable','服务端'],
    ['model_response_invalid','格式'],
  ])('%s 给出可行动提示',(code,keyword)=>expect(modelFailure(code)).toContain(keyword));
  test('未知或非字符串诊断码不猜测',()=>{
    expect(modelFailure('private-upstream-body')).toBeUndefined();
    expect(modelFailure(null)).toBeUndefined();
  });
});
