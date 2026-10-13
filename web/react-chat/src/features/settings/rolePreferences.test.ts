import {describe, expect, it} from 'vitest';
import {applyRolePreferences, DEFAULT_ROLE_PREFERENCES, readRolePreferences} from './rolePreferences';

describe('结构化角色偏好', () => {
  it('旧提示词默认保持关闭且保存时可以无损保留', () => {
    const prompt = '原来的角色规则\n第二行';
    expect(readRolePreferences(prompt).enabled).toBe(false);
    expect(applyRolePreferences(prompt, DEFAULT_ROLE_PREFERENCES, false)).toBe(prompt);
  });

  it('写入后可以回读，重复保存不会叠加受管区块', () => {
    const preferences = {...DEFAULT_ROLE_PREFERENCES, userAddress:'小林', responseLength:'brief' as const};
    const first = applyRolePreferences('原来的角色规则', preferences, true);
    const second = applyRolePreferences(first, {...preferences, emojiFrequency:'none'}, true);
    expect(readRolePreferences(second)).toEqual({enabled:true, preferences:{...preferences, emojiFrequency:'none'}});
    expect(second.match(/LongMemory 控制台表达偏好 v1/g)).toHaveLength(1);
    expect(second).toContain('原来的角色规则');
  });

  it('关闭后只移除受管偏好，不删除手写提示词', () => {
    const managed = applyRolePreferences('手写提示词', DEFAULT_ROLE_PREFERENCES, true);
    expect(applyRolePreferences(managed, DEFAULT_ROLE_PREFERENCES, false)).toBe('手写提示词');
  });
});
