import {afterEach,describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi} from './api';
import {PersonaApp} from './PersonaApp';
import {createConsoleQueryClient} from './queryClient';

afterEach(() => vi.restoreAllMocks());

describe('L3 用户画像页', () => {
  test('只读打开不写入，显式填写和选源后才创建候选', async () => {
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const calls:Array<[string,string|undefined,unknown]> = [];
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(path:string,method?:string,body?:unknown) => {
      calls.push([path,method,body]);
      if(path==='/api/memory-config') return {configured:true,database:'synthetic.db',allow_persona_management:true,persona_model_preview_available:false,persona_model:null};
      if(path.startsWith('/api/personas?')) return {items:[],total:0,limit:100,offset:0};
      if(path==='/api/persona-source-options') return {l1:[{layer:'l1',id:'l1-a',subject_id:'user:self',content:'用户明确希望先被倾听。',recorded_at:'2026-09-06T10:00:00Z'}],l2:[],selection_is_semantic:false};
      if(path==='/api/personas'&&method==='POST') return {id:'persona-1'};
      if(path==='/api/personas/persona-1') return {id:'persona-1',subject_id:'user:self',kind:'interaction_style',basis:'user_declared',label:'建议前先倾听',statement:'用户希望助手先倾听，再询问是否需要建议。',generated_at:'2026-09-06T10:00:00Z',valid_from:null,valid_to:null,status:'candidate',generator_name:'manual_console',generator_version:'1',revision:1,audit:{source_count:1,source_message_count:1,observation_day_count:1},sources:[],lifecycle_events:[]};
      throw new Error(`unexpected ${method??'GET'} ${path}`);
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><PersonaApp/></MemoryRouter></QueryClientProvider>);
    const create=await screen.findByRole('button',{name:'新建 L3 候选'});
    await waitFor(() => expect(create.hasAttribute('disabled')).toBe(false));
    expect(calls.filter(([,method])=>method==='POST')).toHaveLength(0);
    fireEvent.click(create);
    fireEvent.change(screen.getByLabelText('简短标签'),{target:{value:'建议前先倾听'}});
    fireEvent.change(screen.getByLabelText('画像断言'),{target:{value:'用户希望助手先倾听，再询问是否需要建议。'}});
    fireEvent.mouseDown(screen.getByLabelText('画像证据来源'));
    fireEvent.click(await screen.findByText(/L1 · 用户明确希望先被倾听/));
    fireEvent.click(screen.getByRole('button',{name:'创建待复核候选'}));
    await waitFor(() => expect(calls.filter(([path,method])=>path==='/api/personas'&&method==='POST')).toHaveLength(1));
    const body=calls.find(([path,method])=>path==='/api/personas'&&method==='POST')?.[2] as {basis:string;creation_kind:string;sources:Array<{layer:string;id:string}>};
    expect(body.basis).toBe('user_declared');
    expect(body.creation_kind).toBe('manual');
    expect(body.sources).toEqual([{layer:'l1',id:'l1-a'}]);
    view.unmount();client.clear();
  });

  test('模型调用必须二次确认，返回内容只填入草稿而不自动保存', async () => {
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const calls:Array<[string,string|undefined,unknown]> = [];
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(path:string,method?:string,body?:unknown) => {
      calls.push([path,method,body]);
      if(path==='/api/memory-config') return {configured:true,database:'synthetic.db',allow_persona_management:true,persona_model_preview_available:true,persona_model:'synthetic-model'};
      if(path.startsWith('/api/personas?')) return {items:[],total:0,limit:100,offset:0};
      if(path==='/api/persona-source-options') return {l1:[{layer:'l1',id:'l1-a',subject_id:'user:self',content:'用户明确希望先被倾听。',recorded_at:'2026-09-06T10:00:00Z'}],l2:[],selection_is_semantic:false};
      if(path==='/api/persona-proposals'&&method==='POST') return {kind:'interaction_style',basis:'user_declared',label:'建议前先倾听',statement:'用户希望助手先倾听，再询问是否需要建议。',sources:[{layer:'l1',id:'l1-a'}],generator_name:'model_assisted_console',generator_version:'l3-persona-preview-v1',model:'synthetic-model',persisted:false};
      throw new Error(`unexpected ${method??'GET'} ${path}`);
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><PersonaApp/></MemoryRouter></QueryClientProvider>);
    const create=await screen.findByRole('button',{name:'新建 L3 候选'});
    await waitFor(()=>expect(create.hasAttribute('disabled')).toBe(false));
    fireEvent.click(create);
    fireEvent.mouseDown(screen.getByLabelText('画像证据来源'));
    fireEvent.click(await screen.findByText(/L1 · 用户明确希望先被倾听/));
    fireEvent.click(screen.getByRole('button',{name:'让模型生成不落库草稿'}));
    expect(calls.filter(([path])=>path==='/api/persona-proposals')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button',{name:'生成不落库草稿'}));
    await waitFor(()=>expect(calls.filter(([path])=>path==='/api/persona-proposals')).toHaveLength(1));
    expect((screen.getByLabelText('简短标签') as HTMLInputElement).value).toBe('建议前先倾听');
    expect(calls.filter(([path])=>path==='/api/personas')).toHaveLength(0);
    view.unmount();client.clear();
  });
});
