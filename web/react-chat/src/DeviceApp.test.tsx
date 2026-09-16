import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi} from './api';
import {DeviceApp} from './DeviceApp';
import {createConsoleQueryClient} from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('设备与状态页', () => {
  test('等待提示与真正答案单独展示且搜索失败不冒充成功', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1, ready:true, read_volume_supported:false, set_volume_supported:false,
      voice_feedback:{version:1,kind:'web',status:'query_failed',cue_state:'sent',
        query_ms:2500,first_feedback_ms:910,first_answer_ms:4900},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('等待反馈与真正答案')).toBeTruthy();
    expect(screen.getByText('0.91 秒')).toBeTruthy();
    expect(screen.getByText('4.90 秒')).toBeTruthy();
    expect(screen.getByText('2.50 秒')).toBeTruthy();
    expect(screen.getByText(/不能据此声称已查到最新信息/)).toBeTruthy();
    expect(screen.getByText(/等待提示不算作真正答案/)).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('设备离线时显示唤醒提示并禁止音量操作', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count: 0,
      ready: false,
      read_volume_supported: false,
      set_volume_supported: false,
      allowed_volume: {minimum: 5, maximum: 100},
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('请唤醒圆屏')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', {name:'读取当前值'}).hasAttribute('disabled')).toBe(true));
    expect(screen.getByText('电池与充电')).toBeTruthy();
    expect(screen.getAllByText('尚未读取').length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText(/点击页面右上角“读取设备快照”取得当前值/)).toBeTruthy();
    expect(screen.getByText(/当前连接还没有可用的完整时序/)).toBeTruthy();
    expect(screen.getByText(/不需要重新配网/)).toBeTruthy();
    view.unmount();
    client.clear();
  });

  test('快照标明读取时间且音量刻度使用固件允许上限', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async path => {
      if (path === '/api/device/snapshot') return {
        volume: 30, battery: {level: 72, charging: true}, network: {signal: 'strong'},
      };
      return {
        connection_count: 1, ready: true, read_volume_supported: true, set_volume_supported: true,
        read_status_supported: true, set_brightness_supported: false, set_theme_supported: false,
        allowed_volume: {minimum: 5, maximum: 100},
      };
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);

    await waitFor(() => expect(screen.getByText('已连接')).toBeTruthy());
    expect(screen.getByText('/ 100')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: '读取设备快照'}));
    expect(await screen.findByText('72% · 充电中')).toBeTruthy();
    expect(screen.getAllByText('固件未上报').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/读取于 .*不是持续监测；为保护隐私不显示 Wi‑Fi 名称/)).toBeTruthy();
    expect(screen.getByText('单次读取')).toBeTruthy();

    view.unmount();
    client.clear();
  });

  test('展示旧版脱敏首句分段并明确输入侧尚未测量', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1, ready:true, read_volume_supported:true, set_volume_supported:true,
      read_status_supported:true, set_brightness_supported:false, set_theme_supported:false,
      allowed_volume:{minimum:5,maximum:100},
      voice_latency:{version:2,state:'first_audio_sent',started_at:'2026-09-10T01:00:00+00:00',tts_backend:'voxcpm2',timings_ms:{
        memory_ready_ms:80,llm_requested_ms:90,llm_first_output_ms:590,tts_started_ms:790,
        audio_ready_ms:1790,first_audio_sent_ms:1810,response_completed_ms:2100,
      },tts_segments:[
        {index:1,started_ms:790,completed_ms:1790,duration_ms:1000},
        {index:2,started_ms:1800,completed_ms:4200,duration_ms:2400},
      ]},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('最近一次圆屏首句时序')).toBeTruthy();
    expect(await screen.findByText('本轮最长已测区段：TTS 生成与编码')).toBeTruthy();
    expect(screen.getByText(/这是观测到的最长区段，不等于已经证明它是性能根因/)).toBeTruthy();
    expect(screen.getByText('1.00 秒')).toBeTruthy();
    expect(screen.getByText(/样本开始于/)).toBeTruthy();
    expect(screen.getAllByText('旧样本未测').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/不包含设备上行网络，也不代表扬声器真正开始出声/)).toBeTruthy();
    expect(screen.getByText(/当前后端：VoxCPM2/)).toBeTruthy();
    expect(screen.getByText('第 1 段 · 1.00 秒')).toBeTruthy();
    expect(screen.getByText('第 2 段 · 2.40 秒')).toBeTruthy();
    expect(screen.getByText(/不保存该段文字或音频/)).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('V5 显示停嘴、VAD、ASR 和体感总时长', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,
      voice_latency:{version:5,state:'first_audio_sent',response_path:'model',started_at:'2026-09-14T10:00:00+00:00',tts_backend:'cosyvoice3',
        input_timings_ms:{vad_endpoint_ms:700,asr_processing_ms:300},timings_ms:{
          memory_ready_ms:50,llm_requested_ms:55,llm_first_output_ms:1055,tts_started_ms:1100,
          audio_ready_ms:2500,first_audio_sent_ms:2510,response_completed_ms:1800,
        },tts_segments:[{index:1,started_ms:1100,completed_ms:2500,duration_ms:1400}]},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('停嘴 → VAD 结束')).toBeTruthy();
    expect(screen.getByText('ASR 识别处理')).toBeTruthy();
    expect(screen.getByText('停嘴 → 首包发送')).toBeTruthy();
    expect(screen.getByText('3.51 秒')).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('预识别后零等待不显示为听写模型零耗时，也不展示候选正文', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,
      voice_latency:{version:6,state:'first_audio_sent',response_path:'model',started_at:'2026-09-15T10:00:00+00:00',tts_backend:'cosyvoice3',
        input_timings_ms:{vad_endpoint_ms:700,asr_processing_ms:0},timings_ms:{
          memory_ready_ms:50,llm_requested_ms:55,llm_first_output_ms:1055,tts_started_ms:1100,
          audio_ready_ms:2500,first_audio_sent_ms:2510,response_completed_ms:1800,
        },tts_segments:[]},
      voice_asr_prefetch:{version:1,enabled:true,started:2,reused:1,invalidated:0,skipped_busy:0,failed:0,fallback:0,
        latest_status:'reused',latest_prefetch_ms:230,latest_formal_wait_ms:0,latest_model_queue_ms:0,latest_overlap_ms:230,
        text:'SYNTHETIC_PRIVATE_CANDIDATE'},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('停嘴确认后的听写等待')).toBeTruthy();
    expect(screen.queryByText('ASR 识别处理')).toBeNull();
    expect(screen.getByText(/已提前计算 230 ms，当前连接已复用 1 次/)).toBeTruthy();
    expect(screen.getByText(/0 秒不代表模型没有耗时/)).toBeTruthy();
    expect(screen.getByText('3.21 秒')).toBeTruthy();
    expect(screen.queryByText(/SYNTHETIC_PRIVATE_CANDIDATE/)).toBeNull();
    view.unmount(); client.clear();
  });

  test.each([undefined,{version:1,enabled:false},{version:1,enabled:true,latest_prefetch_ms:null}])(
    '未启用或尚无预识别记录时保留原计时视图：%j', async (prefetch) => {
      vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
      vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
        connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,
        voice_latency:{version:5,state:'first_audio_sent',response_path:'model',started_at:'2026-09-15T10:00:00+00:00',tts_backend:'cosyvoice3',
          input_timings_ms:{vad_endpoint_ms:700,asr_processing_ms:230},timings_ms:{
            memory_ready_ms:50,llm_requested_ms:55,llm_first_output_ms:1055,tts_started_ms:1100,
            audio_ready_ms:2500,first_audio_sent_ms:2510,response_completed_ms:1800,
          },tts_segments:[]},voice_asr_prefetch:prefetch,
      });
      const client=createConsoleQueryClient();
      const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
      expect(await screen.findByText('ASR 识别处理')).toBeTruthy();
      expect(screen.queryByText('停嘴确认后的听写等待')).toBeNull();
      expect(screen.queryByText(/0 秒不代表模型没有耗时/)).toBeNull();
      view.unmount(); client.clear();
    },
  );

  test('把模型 404 显示为回答故障而不是声音故障', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:0, ready:false, read_volume_supported:false, set_volume_supported:false,
      voice_latency:{version:3,state:'failed',started_at:'2026-09-14T07:37:18+00:00',tts_backend:'cosyvoice3',timings_ms:{
        memory_ready_ms:2,llm_requested_ms:3,llm_first_output_ms:null,tts_started_ms:1773,
        audio_ready_ms:5939,first_audio_sent_ms:5941,response_completed_ms:1770,
      },tts_segments:[],failure:{stage:'model',code:'model_http_404',at_ms:1768}},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('模型接口返回 404')).toBeTruthy();
    expect(screen.getByText(/这不是声音模型故障/)).toBeTruthy();
    expect(screen.getByText('回答失败')).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('把封闭寒暄显示为本地预置成功路径', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1, ready:true, read_volume_supported:true, set_volume_supported:true,
      voice_latency:{version:4,state:'first_audio_sent',response_path:'preset',started_at:'2026-09-14T09:00:00+00:00',tts_backend:'cosyvoice3',timings_ms:{
        memory_ready_ms:55,llm_requested_ms:null,llm_first_output_ms:null,tts_started_ms:60,
        audio_ready_ms:95,first_audio_sent_ms:105,response_completed_ms:65,
      },tts_segments:[{index:1,started_ms:60,completed_ms:95,duration_ms:35}]},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('本地预置语音')).toBeTruthy();
    expect(screen.getByText('本轮命中封闭寒暄快速通道')).toBeTruthy();
    expect(screen.getAllByText('已跳过（本地预置）')).toHaveLength(2);
    view.unmount(); client.clear();
  });

  test('显示不播放且不保存正文的预测影子统计', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,
      voice_prediction_shadow:{version:1,state:'candidate_waiting',opportunities:3,
        evaluated:2,hits:1,misses:1,last_result:'pending'},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('预测式语音 · 影子观察')).toBeTruthy();
    expect(screen.getByText('当前不会提前播放')).toBeTruthy();
    expect(screen.getByText('50%')).toBeTruthy();
    expect(screen.getByText('等待下一句')).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('明确显示记忆协议失败发生在模型请求之前', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1, ready:true, read_volume_supported:true, set_volume_supported:true,
      voice_latency:{version:3,state:'failed',started_at:'2026-09-14T08:08:15+00:00',tts_backend:'cosyvoice3',timings_ms:{
        memory_ready_ms:null,llm_requested_ms:null,llm_first_output_ms:null,tts_started_ms:null,
        audio_ready_ms:null,first_audio_sent_ms:null,response_completed_ms:35,
      },tts_segments:[],failure:{stage:'memory',code:'memory_response_invalid',at_ms:34}},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('圆屏记忆协议不匹配')).toBeTruthy();
    expect(screen.getByText(/回答模型尚未收到请求/)).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('停止当前回答只声称服务端中止而不伪造设备回执', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const request=vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path) => {
      if (path === '/api/device/speech/stop') return {
        operation_id:'c'.repeat(32),state:'stop_sent',server_interrupted:true,
        device_acknowledgement:'unavailable',
      };
      return {
        connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,
        read_status_supported:true,set_brightness_supported:false,set_theme_supported:false,
        stop_speech_supported:true,allowed_volume:{minimum:5,maximum:100},
      };
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    const button=await screen.findByRole('button',{name:'停止当前回答'});
    await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
    fireEvent.click(button);
    expect(await screen.findByText('已中止服务端回答')).toBeTruthy();
    expect(screen.getByText(/设备协议没有播放停止回执/)).toBeTruthy();
    expect(request).toHaveBeenCalledWith('/api/device/speech/stop','POST');
    view.unmount(); client.clear();
  });

  test('自然打断诊断显示真实阻塞层而不提供伪开启按钮', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,
      read_status_supported:true,set_brightness_supported:false,set_theme_supported:false,
      allowed_volume:{minimum:5,maximum:100},
      natural_interruption:{version:1,state:'blocked',device_aec_advertised:true,
        server_aec_active:true,timestamped_audio_supported:false,listen_mode:'realtime',
        reason:'timestamp_transport_unavailable'},
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><DeviceApp/></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByText('直连传输缺少时间戳配对')).toBeTruthy();
    expect(screen.getByText('时间戳音频传输').parentElement?.textContent).toContain('未满足');
    expect(screen.queryByRole('button',{name:/开启 AEC/})).toBeNull();
    expect(screen.getByText(/不会把控制台按钮停止算作自然语音打断/)).toBeTruthy();
    view.unmount(); client.clear();
  });
});
