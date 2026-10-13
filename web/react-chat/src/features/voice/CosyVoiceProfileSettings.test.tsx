import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, test, vi} from 'vitest';
import {ApiError, ChatApi} from '../../api';
import {CosyVoiceProfileSettings} from './CosyVoiceProfileSettings';

const profile = {version: 1, reference_id: null, transcript: '', style: ''};
const snapshot = {profile, profile_digest: 'a'.repeat(64), references: [], preview_text: '固定合成测试文本', service_state: 'ready', activation: 'next_synthesis'};
beforeEach(() => vi.stubGlobal('URL', class extends URL {
  static createObjectURL() {return 'blob:synthetic-voice';}
  static revokeObjectURL() {}
}));
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals();});

describe('CosyVoice 日用声线', () => {
  test('读取不写入，试听草稿不保存，明确保存带摘要且下一次合成生效', async () => {
    const api = new ChatApi();
    const request = vi.spyOn(api, 'request').mockResolvedValue(snapshot);
    const preview = vi.spyOn(api, 'cosyVoicePreview').mockResolvedValue(new Blob(['RIFF-synthetic'], {type: 'audio/wav'}));
    render(<CosyVoiceProfileSettings api={api} disabled={false}/>);
    await screen.findByText('固定试听文本：固定合成测试文本');
    expect(request.mock.calls.every(call => call[1] === undefined)).toBe(true);
    fireEvent.click(screen.getByRole('button', {name: '温柔亲切'}));
    fireEvent.click(screen.getByRole('button', {name: '试听草稿'}));
    await waitFor(() => expect(preview).toHaveBeenCalledWith({...profile, style: '温柔亲切地说话'}));
    expect(await screen.findByText(/尚未保存到日用声线/)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', {name: '保存日用声线'}));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/voice-profile', 'POST', {profile: {...profile, style: '温柔亲切地说话'}, expected_profile_digest: snapshot.profile_digest}));
    expect(await screen.findByText(/从下一次合成开始使用/)).toBeTruthy();
  });

  test('保存冲突保留草稿，不自动重试写入', async () => {
    const api = new ChatApi();
    const request = vi.spyOn(api, 'request').mockResolvedValue(snapshot);
    render(<CosyVoiceProfileSettings api={api} disabled={false}/>);
    await screen.findByText('固定试听文本：固定合成测试文本');
    fireEvent.change(screen.getByLabelText('表达指令（可留空）'), {target: {value: '平静'}});
    request.mockRejectedValueOnce(new ApiError('voice_profile_changed', 409));
    fireEvent.click(screen.getByRole('button', {name: '保存日用声线'}));
    expect(await screen.findByText(/声音档案已在其他页面修改/)).toBeTruthy();
    expect((screen.getByLabelText('表达指令（可留空）') as HTMLInputElement).value).toBe('平静');
    expect(request).toHaveBeenCalledTimes(2);
  });

  test('恢复原声线仅修改草稿', async () => {
    const api = new ChatApi();
    const request = vi.spyOn(api, 'request').mockResolvedValue({...snapshot, profile: {...profile, style: '开心'}});
    render(<CosyVoiceProfileSettings api={api} disabled={false}/>);
    await screen.findByDisplayValue('开心');
    fireEvent.click(screen.getByRole('button', {name: '恢复原声线草稿'}));
    expect((screen.getByLabelText('表达指令（可留空）') as HTMLInputElement).value).toBe('');
    expect(screen.getByText(/保存后才会生效/)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(1);
  });

  test('上传进入参考库和草稿，不自动保存日用声线', async () => {
    const api = new ChatApi();
    const item = {id: 'f'.repeat(32), label: '合成录音', transcript: '这是合成录音。', duration_seconds: 3, sha256: 'd'.repeat(64)};
    const request = vi.spyOn(api, 'request').mockResolvedValueOnce(snapshot).mockResolvedValue({item, references: [item]});
    render(<CosyVoiceProfileSettings api={api} disabled={false}/>);
    await screen.findByText('固定试听文本：固定合成测试文本');
    fireEvent.change(screen.getByLabelText('参考录音文件'), {target: {files: [new File(['RIFF-synthetic'], '合成录音.wav', {type: 'audio/wav'})]}});
    fireEvent.change(screen.getByLabelText('录音原文'), {target: {value: item.transcript}});
    fireEvent.click(screen.getByRole('button', {name: '上传到参考库'}));
    expect(await screen.findByText(/录音已加入参考库/)).toBeTruthy();
    expect(request.mock.calls[1][0]).toBe('/api/voice-references');
    expect(request.mock.calls.some(call => call[0] === '/api/voice-profile' && call[1] === 'POST')).toBe(false);
  });
});
