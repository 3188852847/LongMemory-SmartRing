import {describe,expect,test} from 'vitest';
import type {TTSBenchmarkCase,TTSBenchmarkRun} from './api';
import {buildTTSComparison} from './ttsBenchmarkComparison';

const cases:TTSBenchmarkCase[]=[
  {id:'short_reply',label:'短回复',text:'合成文本',purpose:'合成目的',text_chars:4},
  {id:'numbers',label:'数字',text:'一二三',purpose:'数字检查',text_chars:3},
];
function run(backend:string,caseId:string,completed:number,duration=1,nearSilent=false):TTSBenchmarkRun {
  return {id:`${backend}${caseId}${completed}`.padEnd(32,'0').slice(0,32),backend,case_id:caseId,
    started_at:'2026-09-11T00:00:00Z',adapter_delivery:'buffered',
    first_audio_available_ms:completed,completed_ms:completed,audio_bytes:1000,content_type:'audio/wav',
    wave:{duration_seconds:duration,sample_rate_hz:16000,channels:1,sample_width_bits:16,rms:100,peak:1000,near_silent:nearSilent}};
}

describe('TTS 同条件探索性汇总',()=>{
  test('按后端和固定用例隔离，并以中位数抵抗单次极端值',()=>{
    const rows=buildTTSComparison(cases,[
      run('sanotts','short_reply',900),run('sanotts','short_reply',1000),run('sanotts','short_reply',9000),
      run('edge','short_reply',1500),run('sanotts','numbers',1200),
    ]);
    const sanoShort=rows.find(item=>item.backend==='sanotts'&&item.caseId==='short_reply')!;
    expect(sanoShort).toMatchObject({sampleCount:3,medianFirstAudioMs:1000,medianCompletedMs:1000,medianRealtimeFactor:1,readiness:'ready'});
    expect(rows.find(item=>item.backend==='edge')?.readiness).toBe('needs_samples');
    expect(rows).toHaveLength(3);
  });

  test('保留近静音故障计数，缺少可解码时长时不伪造实时系数',()=>{
    const withoutWave={...run('edge','short_reply',800),wave:null};
    const rows=buildTTSComparison(cases,[withoutWave,run('edge','short_reply',900,1,true)]);
    expect(rows[0]).toMatchObject({nearSilentCount:1,medianRealtimeFactor:0.9});
  });
});
