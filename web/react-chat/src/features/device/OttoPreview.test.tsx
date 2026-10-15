import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from '../../api';
import {createConsoleQueryClient} from '../../app/queryClient';
import {OttoPreview, ottoNames, resolveOttoFace} from './OttoPreview';

afterEach(()=>{vi.restoreAllMocks();delete document.documentElement.dataset.motion;});
function mount(valid=ottoNames as readonly string[], interaction:'idle'|'thinking'='idle') {
  Object.defineProperty(document,'hidden',{configurable:true,value:false});
  vi.spyOn(ChatApi.prototype,'request').mockResolvedValue({commit:'fixed',valid_count:valid.length,items:ottoNames.map(name=>({name,valid:valid.includes(name)}))});
  return render(<QueryClientProvider client={createConsoleQueryClient()}><OttoPreview ready interaction={interaction} system="normal" caption="网页阶段"/></QueryClientProvider>);
}

describe('真实 Otto 预览',()=>{
  test('设备显示优先级与情绪隔离映射',()=>{
    expect(resolveOttoFace('thinking','normal','happy',false)).toBe('thinking');
    expect(resolveOttoFace('speaking','normal','happy',false)).toBe('happy');
    expect(resolveOttoFace('listening','normal','happy',false)).toBe('neutral');
    expect(resolveOttoFace('speaking','network_offline','happy',false)).toBe('sad');
    expect(resolveOttoFace('speaking','model_unavailable','happy',false)).toBe('confused');
    expect(resolveOttoFace('speaking','provisioning','happy',false)).toBe('neutral');
    expect(resolveOttoFace('interrupted','normal','happy',true)).toBe('surprised');
    expect(resolveOttoFace('interrupted','normal','happy',false)).toBe('neutral');
  });
  test('播放与暂停切换真实循环/单帧路径，解码失败回退平静',async()=>{
    mount(ottoNames,'thinking');
    const image=await screen.findByRole('img',{name:/^Otto /});
    expect(image.getAttribute('src')).toBe('/api/otto-preview/thinking/loop.gif');
    fireEvent.click(screen.getByRole('button',{name:'暂停动画'}));
    expect(screen.getByRole('img',{name:/^Otto /}).getAttribute('src')).toBe('/api/otto-preview/thinking/still.gif');
    fireEvent.error(screen.getByRole('img',{name:/^Otto /}));
    expect(screen.getByRole('img',{name:/^Otto /}).getAttribute('src')).toBe('/api/otto-preview/neutral/still.gif');
    fireEvent.error(screen.getByRole('img',{name:/^Otto /}));
    expect(screen.queryByRole('img',{name:/^Otto /})).toBeNull();
    expect(screen.getByText('素材不可用')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'重新核对素材'}));
    await waitFor(()=>expect(screen.getByRole('img',{name:/^Otto /}).getAttribute('src')).toContain('thinking/still.gif'));
  });
  test('减少动态从第一次渲染即请求单帧，缺素材不伪装几何眼睛',async()=>{
    document.documentElement.dataset.motion='reduce';
    mount(['neutral'],'thinking');
    expect((await screen.findByRole('img',{name:/^Otto /})).getAttribute('src')).toBe('/api/otto-preview/neutral/still.gif');
    expect(screen.getByText('可用素材 1/21')).toBeTruthy();
    expect(screen.getByText(/thinking 不可用，回退平静/)).toBeTruthy();
  });
  test('空素材有明确文字与重试入口，没有设备写请求',async()=>{
    mount([]);
    expect(await screen.findByText('可用素材 0/21')).toBeTruthy();
    expect(screen.queryByRole('img',{name:/^Otto /})).toBeNull();
    expect(screen.getByText('素材不可用')).toBeTruthy();
    expect(vi.mocked(ChatApi.prototype.request).mock.calls.every(([path,method])=>path==='/api/otto-preview' && method===undefined)).toBe(true);
  });
});
