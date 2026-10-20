"""仅独占维护窗口运行的真实Cosy→HTTP→持续PCM/Opus对照；不调用回答模型。"""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[3]
CASES={
 'greeting':'你好，今天又见面了。',
 'sentences':'下午的阳光落在窗边。我们可以先整理桌面，再慢慢安排接下来的事情。',
 'long':'如果一项任务显得复杂，可以先确认最重要的目标，再把它拆成几个能够逐步检查的小步骤，完成一步以后稍作整理，然后继续下一步。',
 'sparse':'这是一段故意缺少标点的合成测试文字用来观察语音生成如何连续交付声音以及句子末尾能否自然完整地保留下来',
 'mixed':'今天的 meeting 安排在下午三点，先检查 Wi-Fi 和 Python 3.10 环境，再讨论 streaming audio 的进度。',
}


def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--production-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--maintenance-window',action='store_true')
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--max-seconds',type=int,default=900)
    args=p.parse_args();production=args.production_root.resolve();output=args.output.resolve()
    if not args.maintenance_window or not os.environ.get('LONGMEMORY_GPU_WINDOW'):
        raise ValueError('explicit_owned_maintenance_window_required')
    if not output.is_relative_to(ROOT/'data/test-tmp') or output.exists():raise ValueError('new_isolated_output_required')
    if not 1<=args.repeats<=5 or not 60<=args.max_seconds<=1000:raise ValueError('benchmark_bounds_invalid')
    output.mkdir(parents=True);logging.disable(logging.CRITICAL)
    # 严禁基准连外部网络。模型、WeText和参考都只读现有本机路径。
    import socket
    original_connect=socket.socket.connect
    def local_only(sock,address):
        if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1'):
            raise RuntimeError('benchmark_external_network_forbidden')
        return original_connect(sock,address)
    socket.socket.connect=local_only
    from service import CosyVoiceSynthesizer,CosyVoiceHTTPServer
    from windows_qos import apply_current_process_high_qos
    qos=apply_current_process_high_qos()
    source=production/'local/runtime/CosyVoice';model=source/'pretrained_models/Fun-CosyVoice3-0.5B'
    voice=production/'local/runtime/xiaozhi-esp32-server/main/xiaozhi-server';voice_python=voice/'.venv/Scripts/python.exe'
    began=time.monotonic();deadline=began+args.max_seconds
    loading=time.perf_counter()
    synth=CosyVoiceSynthesizer(source,model,profile_root=production,warm_selected_voice=False)
    emit({'stage':'isolated_model_ready','constructor_ready_ms':round((time.perf_counter()-loading)*1000),
          'model_load_ms':round(synth.load_seconds*1000),
          'default_warmup_ms':round(synth.warmup_seconds*1000),
          'stream_runtime':synth.stream_runtime.snapshot()})
    if not synth.stream_runtime.applied:raise RuntimeError('fixed_stream_runtime_unavailable')
    server=CosyVoiceHTTPServer(('127.0.0.1',0),synth)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();rows=[]
    native=[];request_started=[None];case_started=[None];request_index=[0]
    original_wave=synth._wave_bytes;original_stream=synth.stream_chunks
    def observed_wave(speech):
        model_yield_ms=round((time.perf_counter()-request_started[0])*1000,3)
        chunk=original_wave(speech)
        native.append({'at_ms':round((time.perf_counter()-request_started[0])*1000,3),
                       'model_yield_at_ms':model_yield_ms,
                       'case_at_ms':round((time.perf_counter()-case_started[0])*1000,3),
                       'request_index':request_index[0],
                       'audio_ms':speech.numel()*1000/synth._sample_rate})
        return chunk
    def observed_stream(*a,**kw):
        request_started[0]=time.perf_counter()
        request_index[0]+=1
        yield from original_stream(*a,**kw)
    synth._wave_bytes=observed_wave;synth.stream_chunks=observed_stream
    def one(case,mode,repeat,*,cache=False,cancel=None,condition='warm_no_reply_cache',segmented=False):
        if time.monotonic()+50>deadline:raise TimeoutError('benchmark_deadline_reserve')
        # 每个等条件配对用同种子；不把流/非流波形声学差异冒充输出等价。
        seed=2710+repeat;torch=synth._torch;torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
        import random,numpy as np
        random.seed(seed);np.random.seed(seed)
        torch.cuda.reset_peak_memory_stats()
        native.clear();request_index[0]=0;case_started[0]=time.perf_counter()
        cpu_started=time.process_time()
        config={'source_root':str(ROOT),'voice_root':str(voice),'url':f'http://127.0.0.1:{server.server_address[1]}/v1/audio/stream',
          'text':CASES[case],'mode':mode,'cache':cache,'sample_rate':24000,
          'cancel_after_packets':cancel,'segmented':segmented}
        if not cancel:config['audio_output']=str(output/f'{condition}-{case}-{mode}-{repeat}.wav')
        result=subprocess.run([str(voice_python),'-B','-X','utf8',str(Path(__file__).with_name('benchmark_stream_client.py'))],
          input=json.dumps(config).encode(),capture_output=True,cwd=ROOT,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            (output/f'child-error-{len(rows)}.log').write_bytes(result.stderr)
            raise RuntimeError('isolated_real_opus_client_failed')
        row={'case':case,'mode':mode,'repeat':repeat,'condition':condition,'reply_cache':cache,'seed':seed,
             'daily_punctuation_policy':segmented,
             'server_process_cpu_ms':round((time.process_time()-cpu_started)*1000,3),
             **json.loads(result.stdout),'peak_allocated_mib':round(torch.cuda.max_memory_allocated()/1048576,2),
             'peak_reserved_mib':round(torch.cuda.max_memory_reserved()/1048576,2),
             'server_pcm_chunks':list(native),'server_first_pcm_ms':native[0]['at_ms'] if native else None,
             'cleanup':synth.stream_runtime.snapshot()}
        rows.append(row)
        with (output/'samples.jsonl').open('a',encoding='utf-8') as file:file.write(json.dumps(row,ensure_ascii=False)+'\n')
        emit({'stage':'sample_complete','index':len(rows),'case':case,'mode':mode,'condition':condition,
              'first_opus_ms':row['rounds'][0]['first_opus_ms'],'total_ms':row['rounds'][0]['total_ms']})
        assert not synth.stream_runtime.states and not server.generation_gate.locked(),'request_cleanup_not_complete'
        return row
    try:
        one('greeting','incremental',0,condition='first_selected_voice_after_default_warmup')
        selected_warm_seconds=synth.prepare_selected_voice()
        emit({'stage':'selected_stream_prepared','seconds':selected_warm_seconds})
        for repeat in range(args.repeats):
            for case in CASES:
                modes=('buffered','incremental') if repeat%2==0 else ('incremental','buffered')
                for mode in modes:one(case,mode,repeat)
        # 与逐段日用路径同一切段策略，单列其首包与跨段库存缺口；全文已可用。
        # 两个代表句覆盖自然多句和长句，不把该结果称为ASR/LLM整链路延迟。
        for repeat in range(args.repeats):
            for case in ('sentences','long'):
                modes=('buffered','incremental') if repeat%2==0 else ('incremental','buffered')
                for mode in modes:
                    one(case,mode,repeat,condition='daily_segments_text_already_ready',segmented=True)
        one('greeting','incremental',50,cache=True,condition='exact_cache_population')
        one('greeting','incremental',51,cache=True,condition='exact_cache_hit')
        one('long','incremental',60,cancel=3,condition='cancel_then_same_encoder_new_round')
        summary={}
        for mode in ('buffered','incremental'):
            chosen=[row['rounds'][0] for row in rows if row['mode']==mode and row['condition']=='warm_no_reply_cache']
            summary[mode]={}
            for field in ('first_pcm_ms','first_opus_ms','total_ms','rtf','estimated_supply_gap_ms'):
                values=sorted(row[field] for row in chosen)
                summary[mode][field]={'median':statistics.median(values),'max':max(values),'samples':len(values)}
        report={'schema_version':1,'base_commit':'87a25e2fd2c9b4486267dd3469fca354c12925a1',
          'candidate_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
          'comparison':'same candidate process and model; buffered reproduces complete-segment delivery barrier; not a separate untouched old executable',
          'source_commit':subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD']).decode().strip(),
          'gpu':synth._torch.cuda.get_device_name(0),'runtime':synth.runtime_info,'qos':qos,
          'default_warmup_seconds':synth.warmup_seconds,'selected_stream_warmup_seconds':selected_warm_seconds,
          'model_load_seconds':synth.load_seconds,'profile_identity':synth.selected_warmup_identity,
          'summary':summary,'sample_count':len(rows),'rows':rows,'case_texts':CASES,
          'physical_playback_verified':False,'full_asr_memory_llm_chain_measured':False,'duration_seconds':time.monotonic()-began}
        report['per_case']={}
        for case in CASES:
            report['per_case'][case]={}
            for mode in ('buffered','incremental'):
                group=[row for row in rows if row['case']==case and row['mode']==mode and row['condition']=='warm_no_reply_cache']
                report['per_case'][case][mode]={}
                for name in ('first_opus_ms','total_ms','rtf','estimated_supply_gap_ms'):
                    values=[row['rounds'][0][name] for row in group]
                    report['per_case'][case][mode][name]={'median':statistics.median(values),'max':max(values),'samples':len(values)}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit({'stage':'benchmark_complete','sample_count':len(rows),'summary':summary,'report':str(output/'report.json')})
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)


if __name__=='__main__':main()
