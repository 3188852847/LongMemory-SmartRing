export type SendShortcut = 'enter' | 'ctrl_enter';

const STORAGE_KEY = 'longmemory:chat-send-shortcut:v1';

export function loadSendShortcut(storage: Pick<Storage, 'getItem'> | undefined = globalThis.localStorage): SendShortcut {
  try {
    return storage?.getItem(STORAGE_KEY) === 'ctrl_enter' ? 'ctrl_enter' : 'enter';
  } catch {
    return 'enter';
  }
}

export function saveSendShortcut(value: SendShortcut, storage: Pick<Storage, 'setItem'> | undefined = globalThis.localStorage) {
  try {
    storage?.setItem(STORAGE_KEY, value);
  } catch {
    // 浏览器禁用本地存储时仅在当前页面生效，不影响聊天。
  }
}

/** 中文输入法仍在组词时不能发送；两种快捷键都保留 Shift+Enter 换行。 */
export function shouldSendFromKeyboard(event: {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  isComposing: boolean;
}, shortcut: SendShortcut) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return false;
  return shortcut === 'enter' ? !event.ctrlKey && !event.metaKey : event.ctrlKey || event.metaKey;
}
