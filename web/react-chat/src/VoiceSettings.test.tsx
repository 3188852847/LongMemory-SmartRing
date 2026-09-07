import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, test, vi} from 'vitest';
import {ChatApi} from './api';
import {VoiceSettings} from './VoiceSettings';

afterEach(() => vi.restoreAllMocks());

describe('VoxCPM2 声音设置', () => {
  test('只展示受控参考音频并携带版本摘要保存声音方案', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path, method, body) => {
      if (method === 'POST') {
        expect(path).toBe('/api/voice-settings');
        expect(body).toEqual({
          version: 1,
          reference: 'trial/plain.wav',
          style: '温柔自然',
          cfg_value: 2,
          quality: 'balanced',
          expected_profile_digest: 'a'.repeat(64),
        });
        return {
          profile: {version: 1, reference: 'trial/plain.wav', style: '温柔自然', cfg_value: 2, quality: 'balanced'},
          profile_digest: 'b'.repeat(64),
          references: [{id: null, label: '模型默认声线'}, {id: 'trial/plain.wav', label: 'plain.wav'}],
        };
      }
      expect(path).toBe('/api/voice-settings');
      return {
        backend: 'voxcpm2', voice: null, voices: [], digest: 'c'.repeat(64), text: '合成测试文本',
        config_matches: true, editable: true, service_ready: true,
        profile: {version: 1, reference: 'trial/plain.wav', style: '温柔自然', cfg_value: 2, quality: 'balanced'},
        profile_digest: 'a'.repeat(64),
        references: [{id: null, label: '模型默认声线'}, {id: 'trial/plain.wav', label: 'plain.wav'}],
      };
    });
    const api = new ChatApi();
    render(<VoiceSettings api={api} disabled={false}/>);

    fireEvent.click(screen.getByRole('button', {name: '声音设置'}));
    expect(await screen.findByText('当前配置：VoxCPM2 本地声音')).toBeTruthy();
    expect(screen.getByText('plain.wav')).toBeTruthy();
    expect(screen.getByDisplayValue('温柔自然')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: '保存声音方案'}));

    await waitFor(() => expect(screen.getByText('声音方案已保存，网页和圆屏下一次合成时使用。')).toBeTruthy());
    expect(request).toHaveBeenCalledTimes(2);
  });

  test('本机模型服务未就绪时禁止保存并说明启动方式', async () => {
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      backend: 'voxcpm2', voice: null, voices: [], digest: 'c'.repeat(64), text: '合成测试文本',
      config_matches: true, editable: true, service_ready: false,
      profile: {version: 1, reference: null, style: '', cfg_value: 2, quality: 'balanced'},
      profile_digest: 'a'.repeat(64), references: [{id: null, label: '模型默认声线'}],
    });
    render(<VoiceSettings api={new ChatApi()} disabled={false}/>);

    fireEvent.click(screen.getByRole('button', {name: '声音设置'}));
    expect(await screen.findByText(/请通过统一启动面板选择 VoxCPM2 后启动/)).toBeTruthy();
    expect(screen.getByRole('button', {name: '保存声音方案'}).hasAttribute('disabled')).toBe(true);
  });
});
