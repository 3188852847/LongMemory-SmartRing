import type {TTSBenchmarkCase, TTSBenchmarkRun} from './api';

export interface TTSComparisonRow {
  key:string;
  backend:string;
  caseId:string;
  caseLabel:string;
  cachePolicy:TTSBenchmarkRun['cache_policy'];
  sampleCount:number;
  medianFirstAudioMs:number;
  medianCompletedMs:number;
  medianRealtimeFactor:number|null;
  nearSilentCount:number;
  readiness:'ready'|'needs_samples';
}

function median(values:number[]):number {
  const ordered=[...values].sort((left,right)=>left-right);
  const middle=Math.floor(ordered.length/2);
  return ordered.length%2 ? ordered[middle] : (ordered[middle-1]+ordered[middle])/2;
}

/**
 * 只聚合同一后端、同一固定用例的既有本机记录。它不剔除冷启动、不评价音色，
 * 也不跨用例平均，因此只能作为下一轮实测的探索性摘要。
 */
export function buildTTSComparison(
  cases:TTSBenchmarkCase[],
  runs:TTSBenchmarkRun[],
):TTSComparisonRow[] {
  const labels=new Map(cases.map(item=>[item.id,item.label]));
  const groups=new Map<string,TTSBenchmarkRun[]>();
  for(const run of runs) {
    const key=`${run.backend}\u0000${run.case_id}\u0000${run.cache_policy}`;
    groups.set(key,[...(groups.get(key)??[]),run]);
  }
  return [...groups.entries()].map(([key,items])=>{
    const [backend,caseId,cachePolicy]=key.split('\u0000') as [string,string,TTSBenchmarkRun['cache_policy']];
    const realtimeFactors=items.flatMap(item=>
      item.wave&&item.wave.duration_seconds>0
        ? [item.completed_ms/(item.wave.duration_seconds*1000)]
        : [],
    );
    return {
      key,backend,caseId,caseLabel:labels.get(caseId)??caseId,cachePolicy,
      sampleCount:items.length,
      medianFirstAudioMs:median(items.map(item=>item.first_audio_available_ms)),
      medianCompletedMs:median(items.map(item=>item.completed_ms)),
      medianRealtimeFactor:realtimeFactors.length?median(realtimeFactors):null,
      nearSilentCount:items.filter(item=>item.wave?.near_silent).length,
      readiness:items.length>=3?'ready' as const:'needs_samples' as const,
    };
  }).sort((left,right)=>left.caseLabel.localeCompare(right.caseLabel,'zh-CN')||left.backend.localeCompare(right.backend));
}
