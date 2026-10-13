import {describe,expect,test,vi} from 'vitest';
import {readRoundObservations,roundObservationKey,writeRoundObservations} from './roundDisplayObservations';

describe('真机圆屏人工观察记录',()=>{
  test('按皮肤和清单指纹隔离并限制备注长度',()=>{
    const key=roundObservationKey('rose-night-v1','a'.repeat(64));
    expect(key).toContain('rose-night-v1');
    const getItem=vi.fn().mockReturnValue(JSON.stringify({idle:{observed_at:'2026-09-09T00:00:00Z',note:'x'.repeat(200)},unknown:{}}));
    expect(readRoundObservations({getItem},key).idle?.note).toHaveLength(160);
  });

  test('损坏数据安全降级且存储失败可见',()=>{
    expect(readRoundObservations({getItem:()=>'{bad'},'key')).toEqual({});
    expect(writeRoundObservations({setItem:()=>{throw new Error('disabled');}},'key',{})).toBe(false);
  });
});
