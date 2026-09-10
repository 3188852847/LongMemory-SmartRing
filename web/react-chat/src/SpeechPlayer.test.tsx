import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, test, vi} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {microphoneFailure, SpeechPlayer} from './SpeechPlayer';
import {ApiError} from './api';

const originalAudio = globalThis.Audio;
const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');

describe('网页朗读的麦克风生命周期', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(globalThis, 'Audio', {configurable: true, writable: true, value: originalAudio});
    if (originalMediaDevices) Object.defineProperty(navigator, 'mediaDevices', originalMediaDevices);
  });

  test('开启说话打断只检查授权，不在待机时占用麦克风', async () => {
    const stop = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({getTracks: () => [{stop}]});
    Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: {getUserMedia}});
    const api = {speech: vi.fn()} as never;

    render(<SpeechPlayer api={api} text="合成测试文本"/>);
    fireEvent.click(screen.getByRole('switch'));

    await waitFor(() => expect(screen.getByText('说话打断已开启；麦克风只会在朗读期间启用。')).toBeTruthy());
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(stop).toHaveBeenCalledOnce();
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true');
  });

  test('浏览器不支持麦克风时保持关闭并给出明确提示', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: undefined});
    const api = {speech: vi.fn()} as never;

    render(<SpeechPlayer api={api} text="合成测试文本"/>);
    fireEvent.click(screen.getByRole('switch'));

    await waitFor(() => expect(screen.getByText(/无法启用麦克风打断/)).toBeTruthy());
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
  });

  test('不向页面泄露浏览器麦克风异常原文', () => {
    expect(microphoneFailure(new DOMException('Permission denied by browser internals', 'NotAllowedError')))
      .toContain('麦克风权限未授予');
    expect(microphoneFailure(new DOMException('Raw device failure', 'NotReadableError')))
      .toContain('可能正被其他程序独占');
    expect(microphoneFailure(new Error('secret browser detail'))).not.toContain('secret browser detail');
  });

  test('生成期间点击停止后不播放迟到的音频', async () => {
    let resolveSpeech: (blob: Blob) => void = () => undefined;
    const speech = vi.fn(() => new Promise<Blob>(resolve => {resolveSpeech = resolve;}));
    const audioConstructor = vi.fn();
    Object.defineProperty(globalThis, 'Audio', {configurable: true, writable: true, value: audioConstructor});
    const api = {speech} as never;

    render(<SpeechPlayer api={api} text="合成测试文本"/>);
    fireEvent.click(screen.getByRole('button', {name: '网页朗读'}));
    await waitFor(() => expect(speech).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', {name: /停\s*止/}));
    resolveSpeech(new Blob(['late audio']));

    await waitFor(() => expect(screen.getByText('已停止网页朗读，麦克风已释放。')).toBeTruthy());
    expect(audioConstructor).not.toHaveBeenCalled();
  });

  test('TTS 未就绪时解释原因并直达声音设置', async () => {
    const api = {speech:vi.fn().mockRejectedValue(new ApiError('tts_service_unavailable',503))} as never;
    render(<MemoryRouter><SpeechPlayer api={api} text="合成测试文本"/></MemoryRouter>);
    fireEvent.click(screen.getByRole('button',{name:'网页朗读'}));
    expect(await screen.findByText(/当前 TTS 服务没有就绪/)).toBeTruthy();
    expect(screen.getByRole('link',{name:'打开声音设置'}).getAttribute('href')).toBe('/settings?tab=voice');
  });

  test('成功朗读显示浏览器观察到的合成等待并说明边界', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:synthetic');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    let now = 100;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    class SyntheticAudio {
      paused = false; currentTime = 0;
      onended: (() => void) | null = null; onerror: (() => void) | null = null;
      play = vi.fn().mockResolvedValue(undefined); pause = vi.fn();
    }
    Object.defineProperty(globalThis, 'Audio', {configurable:true,writable:true,value:SyntheticAudio});
    let finishSpeech:(audio:Blob)=>void=()=>undefined;
    const speech = vi.fn(() => new Promise<Blob>(resolve => {finishSpeech=resolve;}));
    const api = {speech} as never;
    render(<SpeechPlayer api={api} text="合成测试文本"/>);

    fireEvent.click(screen.getByRole('button',{name:'网页朗读'}));
    await waitFor(() => expect(speech).toHaveBeenCalledOnce());
    now = 2600;
    finishSpeech(new Blob(['audio']));

    expect(await screen.findByText(/最近一次网页合成等待：2\.50 秒/)).toBeTruthy();
    expect(screen.getByText(/不代表圆屏首句延迟/)).toBeTruthy();
    expect(createObjectURL).toHaveBeenCalledOnce();
  });
});
