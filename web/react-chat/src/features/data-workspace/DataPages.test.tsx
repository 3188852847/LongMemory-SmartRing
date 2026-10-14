import {afterEach,describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {ApiError,ChatApi} from '../../api';
import {createConsoleQueryClient} from '../../app/queryClient';
import {MemoryApp} from '../../pages/MemoryApp';
import {MemoryQualityApp} from '../../pages/MemoryQualityApp';
import {ScenarioApp} from '../../pages/ScenarioApp';
import {PersonaApp} from '../../pages/PersonaApp';
import {DeviceApp} from '../../pages/DeviceApp';
import {ExperimentApp} from '../../pages/ExperimentApp';
import {syntheticResponse} from './syntheticFixtures';

afterEach(()=>vi.restoreAllMocks());
const pages=[
  {name:'记忆',App:MemoryApp,path:'/memories',normal:'合成事实：用户喜欢茶。',empty:'没有符合条件的 L1',failure:'无法读取记忆服务'},
  {name:'质量',App:MemoryQualityApp,path:'/memory-quality',normal:'合成问题样本',empty:'目前没有待核对问题',failure:'无法读取质量样本'},
  {name:'场景',App:ScenarioApp,path:'/scenarios',normal:'合成场景',empty:'尚无 L2 生活场景',failure:'无法读取记忆服务'},
  {name:'画像',App:PersonaApp,path:'/personas',normal:'合成画像',empty:'尚无已接受的画像认识',failure:'无法读取记忆服务'},
  {name:'设备',App:DeviceApp,path:'/device',normal:'应用音量',empty:'应用音量',failure:'应用音量'},
  {name:'实验',App:ExperimentApp,path:'/experiments-react',normal:'合成模型',empty:'没有匹配的实验',failure:'实验档案读取失败'},
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
    const view=render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>);
    if(path==='/device') {
      const apply=await screen.findByRole('button',{name:normal});
      await waitFor(()=>expect(apply.hasAttribute('disabled')).toBe(mode!=='normal'));
      if(mode!=='normal')expect(screen.getAllByText('不可控').length).toBeGreaterThan(0);
    }else expect((await screen.findAllByText(new RegExp(mode==='normal'?normal:mode==='empty'?empty:failure))).length).toBeGreaterThan(0);
    expect(request.mock.calls.every(([,method])=>!method || method==='GET')).toBe(true);
    view.unmount();client.clear();
  });
});

test('清空一个实验对照列的编辑不会解除另一列的未保存保护',async()=>{
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  vi.spyOn(ChatApi.prototype,'request').mockImplementation(async url=>{
    const value=syntheticResponse(url,true);
    if(url==='/api/experiments/synthetic-run')return {...value as object,review_enabled:true} as never;
    return value as never;
  });
  const client=createConsoleQueryClient();
  const view=render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/experiments-react?run_id=synthetic-run']}><ExperimentApp/></MemoryRouter></QueryClientProvider>);
  const left=await screen.findByRole('textbox',{name:'no_memory复核理由'});
  const right=await screen.findByRole('textbox',{name:'longmemory_v1复核理由'});
  fireEvent.change(left,{target:{value:'合成左列依据'}});fireEvent.change(right,{target:{value:'合成右列依据'}});
  fireEvent.change(left,{target:{value:''}});
  const guarded=new Event('beforeunload',{cancelable:true});window.dispatchEvent(guarded);
  expect(guarded.defaultPrevented).toBe(true);
  fireEvent.change(right,{target:{value:''}});
  const clean=new Event('beforeunload',{cancelable:true});window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
  view.unmount();client.clear();
});
