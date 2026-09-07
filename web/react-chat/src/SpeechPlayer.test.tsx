import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, test, vi} from 'vitest';
import {SpeechPlayer} from './SpeechPlayer';

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

    await waitFor(() => expect(screen.getByText('当前浏览器不支持麦克风打断测试。')).toBeTruthy());
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('false');
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
});
