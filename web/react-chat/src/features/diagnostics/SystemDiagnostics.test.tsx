import {describe, expect, test} from 'vitest';
import {diagnoseSystem} from './SystemDiagnostics';
import type {Config, DeviceStatus, RuntimeStatus} from '../../api';

const runtime:RuntimeStatus = {enabled:true,state:'ready',reason:null,age_seconds:0.5,services:{console:'ready',voice:'running',voxcpm2:'disabled'}};
const config:Config = {enabled:true,database:'synthetic.db',model:'Synthetic',role:'plain_v1',provider:'openai_compatible',method:'longmemory_v1',retrieval:'keyword',model_health:{state:'available',code:null,checked_at:'2026-09-10T00:00:00Z'}};
const device:DeviceStatus = {connection_count:1,ready:true,read_volume_supported:true,set_volume_supported:true,read_status_supported:true,set_brightness_supported:true,set_theme_supported:true};

describe('系统诊断规则', () => {
  test('当前证据齐全时只给出有限的正常结论', () => {
    expect(diagnoseSystem(runtime, config, device).map(x => x.code)).toEqual(['observed_paths_ready']);
  });

  test('语音未启用不是故障，语音运行但设备离线才给出处理项', () => {
    const textOnly = {...runtime, services:{console:'ready',voice:'disabled',voxcpm2:'disabled'} as RuntimeStatus['services']};
    expect(diagnoseSystem(textOnly, config, {...device,ready:false}).some(x => x.code === 'voice_running_device_offline')).toBe(false);
    expect(diagnoseSystem(runtime, config, {...device,ready:false}).map(x => x.code)).toContain('voice_running_device_offline');
  });

  test('过期启动状态和失败模型不会显示为正常', () => {
    const stale = {...runtime,state:'stale' as const,services:{}};
    const unavailable = {...config,model_health:{state:'unavailable' as const,code:'auth_failed',checked_at:'2026-09-10T00:00:00Z'}};
    const codes = diagnoseSystem(stale, unavailable, device).map(x => x.code);
    expect(codes).toContain('launcher_status_stale');
    expect(codes).toContain('answer_model_unavailable');
    expect(codes).not.toContain('observed_paths_ready');
  });

  test('sanoTTS 未就绪时与 VoxCPM2 分开提示', () => {
    const loading = {...runtime, services:{...runtime.services, sanotts:'running' as const}};
    const findings = diagnoseSystem(loading, config, device);
    expect(findings.map(item => item.code)).toContain('sanotts_loading');
    expect(findings.find(item => item.code === 'sanotts_loading')?.title).toContain('sanoTTS');
  });
});
