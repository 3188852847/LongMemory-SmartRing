import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, test, vi} from 'vitest';
import {ApiError, ChatApi} from '../../api';
import {VoiceSettings, voiceSettingsFailure} from './VoiceSettings';

afterEach(() => vi.restoreAllMocks());

describe('VoxCPM2 声音设置', () => {
  test('把声音边界错误翻译为可执行说明', () => {
    expect(voiceSettingsFailure(new ApiError('voice_not_enabled', 403))).toMatch(/统一启动面板/);
    expect(voiceSettingsFailure(new ApiError('voice_operation_failed_recheck', 409))).toMatch(/重新读取配置/);
    expect(voiceSettingsFailure(new ApiError('private-provider-body', 500))).not.toContain('private-provider-body');
  });

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

  test('sanoTTS 可保存受控语速并如实说明圆屏需重启', async () => {
    const request=vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (_path,method,body)=>{
      if(method==='POST'){
        expect(body).toEqual({speed:1,expected_digest:'d'.repeat(64)});
        return {backend:'sanotts',voice:'xiaoya',voices:[],digest:'e'.repeat(64),text:'合成测试文本',config_matches:true,editable:true,speed:1};
      }
      return {
        backend: 'sanotts', voice: 'xiaoya', voices: [], digest: 'd'.repeat(64),
        text: '合成测试文本', config_matches: true, editable: true, service_ready: true, speed:1.2,
      };
    });
    render(<VoiceSettings api={new ChatApi()} disabled={false}/>);
    fireEvent.click(screen.getByRole('button', {name:'声音设置'}));
    expect(await screen.findByText('当前配置：sanoTTS 本地中文小雅')).toBeTruthy();
    expect(screen.getByText(/当前仍是整段 WAV 生成/)).toBeTruthy();
    expect(screen.getByRole('button', {name:'网页朗读'})).toBeTruthy();
    expect(screen.getByText(/1.20×/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'恢复标准语速草稿'}));
    fireEvent.click(screen.getByRole('button',{name:'保存说话速度'}));
    expect(await screen.findByText(/圆屏语音重启后使用/)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(2);
  });

  test('恢复推荐声音只修改草稿，仍需明确保存', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      backend: 'voxcpm2', voice: null, voices: [], digest: 'c'.repeat(64), text: '合成测试文本',
      config_matches: true, editable: true, service_ready: true,
      profile: {version: 1, reference: 'trial/plain.wav', style: '温柔自然', cfg_value: 2.7, quality: 'quality'},
      profile_digest: 'a'.repeat(64), references: [{id: null, label: '模型默认声线'}, {id:'trial/plain.wav', label:'plain.wav'}],
    });
    render(<VoiceSettings api={new ChatApi()} disabled={false}/>);
    fireEvent.click(screen.getByRole('button', {name:'声音设置'}));
    expect(await screen.findByDisplayValue('温柔自然')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', {name:/恢复推荐声音草稿/}));
    expect((screen.getByPlaceholderText(/年轻女性/) as HTMLInputElement).value).toBe('');
    expect((screen.getByRole('combobox', {name:'参考音色'}) as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/点击保存后才会生效/)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(1);
  });

  test('读取失败时显示声音操作建议而不是技术错误码', async () => {
    vi.spyOn(ChatApi.prototype, 'request').mockRejectedValue(new ApiError('voice_not_enabled', 403));
    render(<VoiceSettings api={new ChatApi()} disabled={false}/>);
    fireEvent.click(screen.getByRole('button', {name: '声音设置'}));
    expect(await screen.findByText(/请从统一启动面板启动圆屏语音后再读取/)).toBeTruthy();
    expect(screen.queryByText(/voice_not_enabled/)).toBeNull();
  });
});
