import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {describe, expect, test, vi} from 'vitest';
import type {ChatApi, Config, ModelHealth} from './api';
import {ModelConnectionSettings} from './ModelConnectionSettings';

const config: Config = {
  enabled:true, database:'synthetic.db', model:'DeepSeek-V4-Flash', role:'plain',
  provider:'openai_compatible', method:'rules', retrieval:'keyword',
  model_endpoint:'http://model.invalid/tenant/v1', insecure_model_transport:true,
  model_health:{state:'unchecked', code:null, checked_at:null},
};

describe('模型连接设置', () => {
  test('展示无密钥端点和明文风险，并只在点击后检测', async () => {
    const health: ModelHealth = {state:'available',code:null,checked_at:'2026-09-08T00:00:00Z'};
    const request = vi.fn(async (path:string) => path === '/api/model-profiles' ? {
      enabled:true,current_profile:'campus',next_start_profile:'official',restart_required:true,
      profiles:[{id:'official',label:'官方 DeepSeek',file_exists:true,base_url:'https://api.deepseek.com/v1',model:'deepseek-chat',timeout_seconds:30,max_tokens:512,allow_http:false,api_key_configured:true}],
    } : health);
    const onHealth = vi.fn();
    render(<ModelConnectionSettings api={{request} as unknown as ChatApi} config={config} disabled={false} onHealth={onHealth}/>);
    expect(screen.getByText('http://model.invalid/tenant/v1')).toBeTruthy();
    expect(screen.getByText('HTTP 明文')).toBeTruthy();
    expect(document.body.textContent).not.toContain('api-secret');
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/model-profiles'));
    fireEvent.click(screen.getByRole('button',{name:'检测当前模型连接'}));
    await waitFor(() => expect(onHealth).toHaveBeenCalledWith(health));
    expect(request).toHaveBeenCalledWith('/api/chat-model/check','POST',{});
    expect(document.body.textContent).not.toContain('synthetic-secret');
  });
});
