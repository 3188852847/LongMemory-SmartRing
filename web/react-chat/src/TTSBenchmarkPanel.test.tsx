import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {afterEach,expect,test,vi} from 'vitest';
import {ChatApi} from './api';
import {TTSBenchmarkPanel} from './TTSBenchmarkPanel';

afterEach(()=>vi.restoreAllMocks());

test('显示当前真实能力并运行固定文本测试',async()=>{
  const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(path,method,body)=>{
    if(method==='POST') {
      expect(body).toEqual({case_id:'short_reply'});
      return {schema_version:1,backend:'voxcpm2',capabilities:{contract_version:2,provider_id:'voxcpm2',display_name:'VoxCPM2',locality:'local',delivery_modes:['buffered'],output_mime_types:['audio/wav'],controls:['reference_voice','style_prompt'],cancellation:'none',max_text_chars:600},case:{id:'short_reply',label:'短回复',text:'好呀，我们慢慢来。',purpose:'观察首句等待',text_chars:9},started_at:'2026-09-11T00:00:00Z',adapter_delivery:'buffered',first_audio_available_ms:4200,completed_ms:4200,audio_bytes:32044,content_type:'audio/wav',wave:{duration_seconds:1.2,sample_rate_hz:48000,channels:1,sample_width_bits:16,rms:0.1,peak:0.5,near_silent:false},limitations:['不含圆屏时间']};
    }
    expect(path).toBe('/api/tts-benchmark');
    return {schema_version:1,backend:'voxcpm2',capabilities:{contract_version:2,provider_id:'voxcpm2',display_name:'VoxCPM2',locality:'local',delivery_modes:['buffered'],output_mime_types:['audio/wav'],controls:['reference_voice','style_prompt'],cancellation:'none',max_text_chars:600},cases:[{id:'short_reply',label:'短回复',text:'好呀，我们慢慢来。',purpose:'观察首句等待',text_chars:9}],execution:{parallel:false,retries:0,stores_chat_or_memory:false}};
  });
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
  render(<QueryClientProvider client={client}><TTSBenchmarkPanel api={new ChatApi()} enabled={true}/></QueryClientProvider>);
  expect(await screen.findByText('完整音频缓冲')).toBeTruthy();
  expect(screen.getByText('不能取消生成')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'运行一次测试'}));
  await waitFor(()=>expect(screen.getAllByText('4200 ms')).toHaveLength(2));
  expect(screen.getByText(/1.20 秒/)).toBeTruthy();
  expect(request).toHaveBeenCalledTimes(2);
});
