import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,describe,expect,test,vi} from 'vitest';
import {ApiError,ChatApi} from '../../api';
import {TTSBackendSettings,ttsBackendFailure} from './TTSBackendSettings';

afterEach(()=>vi.restoreAllMocks());

describe('TTS 下次启动选择',()=>{
  test('安全翻译错误',()=>{
    expect(ttsBackendFailure(new ApiError('tts_backends_disabled',403),'read')).toMatch(/统一启动面板/);
    expect(ttsBackendFailure(new ApiError('private path',500),'write')).not.toContain('private path');
  });

  test('只保存下次启动指针并提示重启',async()=>{
    const backends=[
      {id:'edge',label:'EdgeTTS',description:'联网',local_service:false},
      {id:'sanotts',label:'sanoTTS',description:'本地快速',local_service:true},
    ];
    const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(_path,method,body)=>{
      if(method==='PUT'){
        expect(body).toEqual({backend:'sanotts'});
        return {enabled:true,current_backend:'edge',next_start_backend:'sanotts',voice_running:true,restart_required:true,backends};
      }
      return {enabled:true,current_backend:'edge',next_start_backend:'edge',voice_running:true,restart_required:false,backends};
    });
    render(<TTSBackendSettings api={new ChatApi()} disabled={false}/>);
    await screen.findByText('联网');
    fireEvent.click(screen.getByRole('button',{name:'高级：兼容声音引擎'}));
    fireEvent.mouseDown(screen.getByRole('combobox',{name:'圆屏声音后端'}));
    fireEvent.click(await screen.findByText('sanoTTS（兼容）'));
    fireEvent.click(screen.getByRole('button',{name:'保存下次启动选择'}));
    expect(await screen.findByText('等待重启生效')).toBeTruthy();
    await waitFor(()=>expect(request).toHaveBeenCalledTimes(2));
  });
});
