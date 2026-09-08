import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {describe, expect, test, vi} from 'vitest';
import type {ChatApi, MemoryBackends} from './api';
import {MemoryBackendSettings} from './MemoryBackendSettings';


const initial: MemoryBackends = {
  enabled:true,
  current_backend:'longmemory',
  next_start_backend:'longmemory',
  restart_required:false,
  backends:[
    {id:'longmemory',label:'LongMemory（当前系统）',provider:'LongMemory',description:'分层记忆',persistent:true},
    {id:'xiaozhi_local',label:'小智本地摘要',provider:'mem_local_short',description:'单份摘要',persistent:true},
    {id:'none',label:'无长期记忆（速度基线）',provider:'nomem',description:'不跨会话',persistent:false},
  ],
  xiaozhi:{enabled:true,selected_backend:'longmemory',status:'configured',
           provider_name:'LongMemory',configured_provider:'LongMemory'},
};


describe('圆屏记忆后端设置', () => {
  test('明确区分固件与服务端后端，并把选择延迟到下次启动', async () => {
    const request = vi.fn(async (path:string, method?:string, body?:unknown) => {
      if (method === 'PUT') {
        expect(path).toBe('/api/memory-backends/selection');
        expect(body).toEqual({backend:'xiaozhi_local'});
        return {...initial,next_start_backend:'xiaozhi_local',restart_required:true,
                xiaozhi:{...initial.xiaozhi!,selected_backend:'xiaozhi_local',status:'restart_pending'}};
      }
      return initial;
    });
    render(<MemoryBackendSettings api={{request} as unknown as ChatApi} disabled={false}/>);
    await screen.findByText('这里切换的是圆屏长期记忆，不是圆屏固件');
    fireEvent.mouseDown(screen.getByLabelText('圆屏记忆后端'));
    fireEvent.click(await screen.findByText('小智本地摘要'));
    fireEvent.click(screen.getByRole('button',{name:'保存选择'}));
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('需要重新启动')).toBeTruthy();
    expect(document.body.textContent).toContain('不会共享或迁移数据');
  });
});
