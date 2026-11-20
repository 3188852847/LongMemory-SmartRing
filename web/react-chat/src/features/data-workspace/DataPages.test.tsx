import {afterEach,describe,expect,test,vi} from 'vitest';
import {render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {ApiError,ChatApi} from '../../api';
import {createConsoleQueryClient} from '../../app/queryClient';
import {DeviceApp} from '../../pages/DeviceApp';
import {syntheticResponse} from './syntheticFixtures';
import {KnownMemoryEngine} from '../../tests/memoryEngine';

afterEach(()=>vi.restoreAllMocks());
const pages=[
  {name:'设备',App:DeviceApp,path:'/device',normal:'应用音量',empty:'应用音量',failure:'应用音量'},
];
describe.each(pages)('$name页面合成状态',({App,path,normal,empty,failure})=>{
  test.each(['normal','empty','failure'] as const)('%s：可浏览且没有自动写请求',async mode=>{
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const request=vi.spyOn(ChatApi.prototype,'request').mockImplementation(async (url,method)=>{
      if(method && method!=='GET')throw new Error('只读验收不允许写入');
      if(mode==='failure')throw new ApiError('http_503',503);
      return syntheticResponse(url,mode==='normal') as never;
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><KnownMemoryEngine kind="hy"><App/></KnownMemoryEngine></MemoryRouter></QueryClientProvider>);
    if(path==='/device') {
      const apply=await screen.findByRole('button',{name:normal});
      await waitFor(()=>expect(apply.hasAttribute('disabled')).toBe(mode!=='normal'));
      if(mode!=='normal')expect(screen.getAllByText('不可控').length).toBeGreaterThan(0);
    }else expect((await screen.findAllByText(new RegExp(mode==='normal'?normal:mode==='empty'?empty:failure))).length).toBeGreaterThan(0);
    expect(request.mock.calls.every(([,method])=>!method || method==='GET')).toBe(true);
    view.unmount();client.clear();
  });
});
