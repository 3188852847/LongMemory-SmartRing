import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {describe, expect, test, vi} from 'vitest';
import {ChatApi} from '../../api';
import {PersonalizationOverview} from './PersonalizationOverview';

describe('个性化状态总览', () => {
  test('区分网页选择、真机同步边界，并按需读取声音', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/assistant-role') return {current:{revision:3,name:'爱莉希雅',prompt:'测试提示词',saved_at:null},web:'next_turn',device:'check_required'};
      if (path === '/api/round-skins') return {enabled:true,selected_skin:'gentle',custom_skin_id:'custom',skins:[{id:'gentle',name:'温柔',description:'',schema_version:1,target:{board:'viewe-smartring-plus',width:360,height:360,color_format:'RGB565',skin_api:1},palette:{},face:{},motion:{},manifest_sha256:'a'}],delivery:{console_preview:true,upstream_assets_ota_detected:true,device_apply_supported:true,reason:'',known_firmware_baseline:''}};
      if (path === '/api/proactive-policy') return {enabled:true};
      if (path === '/api/tts-backends') return {enabled:true,current_backend:'edge',next_start_backend:'voxcpm2',voice_running:true,restart_required:true,backends:[]};
      if (path === '/api/voice-settings') return {backend:'voxcpm2',voice:null,service_ready:true,profile:{reference:'trial/plain.wav',style:'温柔',quality:'balanced'},references:[{id:'trial/plain.wav',label:'plain.wav'}]};
      throw new Error(`unexpected path: ${path}`);
    });
    const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
    const select = vi.fn();
    render(<QueryClientProvider client={client}><PersonalizationOverview api={new ChatApi()} ready={true}
      prefs={{theme:'future',size:'normal',motion:'system',density:'comfortable',chatWidth:'focused'}} onSelectTab={select}/></QueryClientProvider>);

    expect(await screen.findByText('爱莉希雅 · 修订 3')).toBeTruthy();
    expect(screen.getByText('当前只是预览选择')).toBeTruthy();
    expect(screen.getByText('真机状态未自动读取')).toBeTruthy();
    expect(screen.getByText(/本次 EdgeTTS；下次 VoxCPM2/)).toBeTruthy();
    expect(screen.getByText('停止并重启语音后')).toBeTruthy();
    expect(request).not.toHaveBeenCalledWith('/api/voice-settings');
    fireEvent.click(screen.getByRole('button', {name:'读取声音状态'}));
    expect(await screen.findByText('本次 EdgeTTS；下次 VoxCPM2 · plain.wav · 均衡')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', {name:/设\s*置/})[0]);
    expect(select).toHaveBeenCalledWith('appearance');
    expect(screen.getAllByRole('link', {name:'打开圆屏外观'})[0].getAttribute('href')).toBe('/display-preview');
    await waitFor(() => expect(request).toHaveBeenCalledTimes(5));
  });

  test('单项读取失败不会隐藏其他个性化事实', async () => {
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/assistant-role') throw new Error('unavailable');
      if (path === '/api/round-skins') return {enabled:true,selected_skin:'default',custom_skin_id:'custom',skins:[],delivery:{console_preview:true,upstream_assets_ota_detected:false,device_apply_supported:false,reason:'',known_firmware_baseline:''}};
      if (path === '/api/proactive-policy') return {enabled:false};
      if (path === '/api/tts-backends') throw new Error('unavailable');
      throw new Error(`unexpected path: ${path}`);
    });
    const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
    render(<QueryClientProvider client={client}><PersonalizationOverview api={new ChatApi()} ready={true}
      prefs={{theme:'light',size:'large',motion:'reduce',density:'compact',chatWidth:'wide'}} onSelectTab={() => undefined}/></QueryClientProvider>);
    expect(await screen.findByText('平静浅色 · 紧凑')).toBeTruthy();
    expect(await screen.findByText('已关闭')).toBeTruthy();
    expect((await screen.findAllByText('读取失败')).length).toBeGreaterThan(0);
  });
});
