import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {ChatApi} from '../api';
import {ExperimentApp} from './ExperimentApp';
import {createConsoleQueryClient} from '../app/queryClient';

afterEach(() => vi.restoreAllMocks());

describe('React 实验档案', () => {
  test('逐题回答按文本展示，不解释为 HTML', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const calls: Array<[string, string | undefined, unknown]> = [];
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path: string, method?: string, body?: unknown) => {
      calls.push([path, method, body]);
      if (method === 'POST') return {revision:1};
      if (path === '/api/experiment-jobs/options') return {enabled:false,real_available:false,retrievals:[],context_default:4000,context_max:16000};
      if (path === '/api/experiment-jobs') return {items:[]};
      if (path === '/api/l1-policy-replay') return {sources:[],replays:[],skipped:0};
      if (path === '/api/experiments') return {items:[{id:'comparison-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',kind:'answers',provider:'fake',model:'fake',dataset:'synthetic',split:'dev',status:'completed',completed:1,total:1,started_at:'2026-09-03T10:00:00Z'}],skipped:0,limited:false};
      if (path.includes('/question?')) return {report_sha256:'a'.repeat(64),source_note:'合成来源',rows:[{group:'longmemory_v1',status:'completed',answer:'<script>不应执行</script>',answer_proxy_pass:false,evidence_complete:true,state_unchanged:true,injected_context:'证据',context:'证据',retrieved:[],sources:[],reference_answer:'参照'}]};
      return {kind:'answers',started_at:'2026-09-03T10:00:00Z',dataset:{name:'synthetic'},split:'dev',status:'completed',groups:[{id:'longmemory_v1',completed:1,total:1,answer_scored:true,answer_pass:0,evidence_scored:1,evidence_pass:1}],reviews:[],questions:[{id:'q1',query:'合成问题'}],ignored_reviews:0,report_sha256:'a'.repeat(64),review_enabled:true};
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><ExperimentApp/></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText('<script>不应执行</script>', undefined, {timeout:5000})).toBeTruthy();
    expect(view.container.querySelector('.answer-text script')).toBeNull();
    expect(screen.getByText(/人工复核均已迁移/)).toBeTruthy();
    fireEvent.change(screen.getByRole('textbox', {name:'longmemory_v1复核理由'}), {target:{value:'依据合成来源'}});
    fireEvent.click(screen.getByRole('button', {name:'保存此题复核'}));
    await waitFor(() => expect(calls.some(([path, method, body]) => path.endsWith('/reviews') && method === 'POST' && (body as {request_id?:string}).request_id)).toBeTruthy());
    view.unmount(); client.clear();
  });

  test('实验预检不会启动，勾选确认后才发送一次启动请求', async () => {
    vi.spyOn(ChatApi.prototype, 'bootstrap').mockResolvedValue(undefined);
    const calls: Array<[string, string | undefined, unknown]> = [];
    vi.spyOn(ChatApi.prototype, 'request').mockImplementation(async (path:string, method?:string, body?:unknown) => {
      calls.push([path,method,body]);
      if (path === '/api/experiment-jobs/options') return {enabled:true,real_available:false,retrievals:[{id:'retrieval-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',dataset:'synthetic',started_at:'2026-09-03T10:00:00Z'}],context_default:4000,context_max:16000};
      if (path === '/api/experiment-jobs') return {items:[]};
      if (path === '/api/l1-policy-replay') return {sources:[],replays:[],skipped:0};
      if (path === '/api/experiment-jobs/prepare') return {quote_id:'q'.repeat(32),retrieval_id:'retrieval-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',groups:['longmemory_v1/original_keyword'],question_count:8,total:8,context_chars:4000,model:{provider:'fake',model:'fake',timeout_seconds:1,max_tokens:64},network:false,insecure_http:false,expires_in_seconds:600};
      if (path === '/api/experiment-jobs/start') return {id:'c'.repeat(32),status:'queued',model:{provider:'fake',model:'fake',timeout_seconds:1,max_tokens:64},total:8,attempts:0,completed:0,failed:0};
      if (path === '/api/experiments') return {items:[],skipped:0,limited:false};
      throw new Error(`unexpected ${method ?? 'GET'} ${path}`);
    });
    const client = createConsoleQueryClient();
    const view = render(<QueryClientProvider client={client}><MemoryRouter><ExperimentApp/></MemoryRouter></QueryClientProvider>);

    fireEvent.click(screen.getByRole('button',{name:'运行实验'}));
    const prepare = await screen.findByRole('button',{name:'预检与核对预算'});
    await waitFor(() => expect(prepare.hasAttribute('disabled')).toBe(false));
    fireEvent.click(prepare);
    expect(await screen.findByText(/Fake 不联网，只验证工程流程/)).toBeTruthy();
    expect(calls.filter(([path]) => path === '/api/experiment-jobs/start')).toHaveLength(0);
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button',{name:'确认启动'}));
    await waitFor(() => expect(calls.filter(([path]) => path === '/api/experiment-jobs/start')).toHaveLength(1));
    const startBody = calls.find(([path]) => path === '/api/experiment-jobs/start')?.[2] as {confirm:boolean;allow_network:boolean;request_id:string};
    expect(startBody.confirm).toBe(true); expect(startBody.allow_network).toBe(false); expect(startBody.request_id).toBeTruthy();
    view.unmount(); client.clear();
  });

  test('L1门控回放在页面本地运行并显示风险指标',async()=>{
    vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
    const calls:Array<[string,string|undefined,unknown]>=[];
    let completed=false;
    vi.spyOn(ChatApi.prototype,'request').mockImplementation(async(path:string,method?:string,body?:unknown)=>{
      calls.push([path,method,body]);
      if(path==='/api/experiment-jobs/options')return {enabled:false,real_available:false,retrievals:[],context_default:4000,context_max:16000};
      if(path==='/api/experiment-jobs')return {items:[]};
      if(path==='/api/experiments')return {items:[],skipped:0,limited:false};
      if(path==='/api/l1-policy-replay'&&method==='POST'){completed=true;return {id:'l1-sufficiency-policy-replay-'+'c'.repeat(32),replayed:false,status:'completed',summary:{}};}
      if(path==='/api/l1-policy-replay')return {sources:[{id:'l1-sufficiency-rescore-'+'a'.repeat(32),protocol:'l1-evidence-sufficiency-rescore-v1',dataset:'l1-v2',total:16,report_sha256:'b'.repeat(64)}],replays:completed?[{id:'l1-sufficiency-policy-replay-'+'c'.repeat(32),status:'completed',source_report_sha256:'b'.repeat(64),report_sha256:'d'.repeat(64),summary:{total_cases:16,completed_cases:16,false_block_cases:0,unsupported_pass_cases:0,original_candidate_count:26,kept_candidate_count:11,removed_candidate_count:15,candidate_reduction_rate:15/26,context_character_reduction_rate:0.550595}}]:[],skipped:0};
      throw new Error(`unexpected ${method??'GET'} ${path}`);
    });
    const client=createConsoleQueryClient();
    const view=render(<QueryClientProvider client={client}><MemoryRouter><ExperimentApp/></MemoryRouter></QueryClientProvider>);
    fireEvent.click(screen.getByRole('button',{name:'L1 策略回放'}));
    const button=await screen.findByRole('button',{name:'运行本地回放'});
    await waitFor(()=>expect(button.hasAttribute('disabled')).toBe(false));
    fireEvent.click(button);
    expect(await screen.findByText('15/26（57.7%）')).toBeTruthy();
    const body=calls.find(([path,method])=>path==='/api/l1-policy-replay'&&method==='POST')?.[2] as {source_id:string;request_id:string};
    expect(body.source_id).toMatch(/^l1-sufficiency-rescore-/);
    expect(body.request_id).toBeTruthy();
    view.unmount();client.clear();
  });
});
