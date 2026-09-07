import {describe, expect, test} from 'vitest';
import {loadSendShortcut, saveSendShortcut, shouldSendFromKeyboard} from './chatInput';

const key = (change: Partial<Parameters<typeof shouldSendFromKeyboard>[0]> = {}) => ({
  key: 'Enter', shiftKey: false, ctrlKey: false, metaKey: false, isComposing: false, ...change,
});

describe('聊天发送快捷键', () => {
  test('Enter 模式保留 Shift 换行并保护中文输入法', () => {
    expect(shouldSendFromKeyboard(key(), 'enter')).toBe(true);
    expect(shouldSendFromKeyboard(key({shiftKey: true}), 'enter')).toBe(false);
    expect(shouldSendFromKeyboard(key({isComposing: true}), 'enter')).toBe(false);
  });

  test('Ctrl+Enter 模式只接受组合键', () => {
    expect(shouldSendFromKeyboard(key(), 'ctrl_enter')).toBe(false);
    expect(shouldSendFromKeyboard(key({ctrlKey: true}), 'ctrl_enter')).toBe(true);
    expect(shouldSendFromKeyboard(key({metaKey: true}), 'ctrl_enter')).toBe(true);
  });

  test('本地存储异常时安全回退为 Enter', () => {
    expect(loadSendShortcut({getItem: () => {throw new Error('blocked');}})).toBe('enter');
    expect(() => saveSendShortcut('ctrl_enter', {setItem: () => {throw new Error('blocked');}})).not.toThrow();
  });
});
