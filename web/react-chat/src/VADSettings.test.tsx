import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,describe,expect,test,vi} from 'vitest';
import {ApiError,ChatApi} from './api';
import {VADSettings,vadSettingsFailure} from './VADSettings';

afterEach(()=>vi.restoreAllMocks());

describe('拾音灵敏度设置',()=>{
  test('解释 VAD 边界且不泄露内部错误',()=>{
    expect(vadSettingsFailure(new ApiError('vad_not_enabled',403))).toMatch(/统一启动面板/);
    expect(vadSettingsFailure(new ApiError('private yaml path',500))).not.toContain('private yaml path');
  });

  test('读取当前档位并携带摘要保存',async()=>{
    const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(path,method,body)=>{
      expect(path).toBe('/api/vad-settings');
      if(method==='PUT'){
        expect(body).toEqual({profile:'close_talk',expected_digest:'a'.repeat(64)});
        return {profile:'close_talk',values:{threshold:.82,threshold_low:.55,min_silence_duration_ms:700},digest:'b'.repeat(64),runtime:'unverified'};
      }
      return {profile:'normal',values:{threshold:.5,threshold_low:.3,min_silence_duration_ms:600},digest:'a'.repeat(64),runtime:'unverified'};
    });
    render(<VADSettings api={new ChatApi()} disabled={false}/>);
    expect(await screen.findByText(/它能减少旁人误触发/)).toBeTruthy();
    fireEvent.click(screen.getByRole('radio',{name:/近讲严格/}));
    fireEvent.click(screen.getByRole('button',{name:'保存拾音档位'}));
    expect(await screen.findByText(/重新启动圆屏语音/)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(2);
  });

  test('自定义数值不会被页面猜测成预设',async()=>{
    vi.spyOn(ChatApi.prototype,'request').mockResolvedValue({
      profile:'custom',values:{threshold:.61,threshold_low:.3,min_silence_duration_ms:600},
      digest:'a'.repeat(64),runtime:'unverified',
    });
    render(<VADSettings api={new ChatApi()} disabled={false}/>);
    expect(await screen.findByText(/当前数值不匹配三个受控预设/)).toBeTruthy();
    await waitFor(()=>expect(screen.getByRole('button',{name:'保存拾音档位'}).hasAttribute('disabled')).toBe(false));
  });
});
