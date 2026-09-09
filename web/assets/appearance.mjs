// 仅保存本浏览器的显示偏好，不保存聊天正文，也不写入长期记忆。
export const KEY = 'longmemory:chat-appearance:v2';
export const LEGACY_KEY = 'longmemory:chat-appearance:v1';
export function normalize(value) {
  return {theme: ['system', 'light', 'dark', 'future'].includes(value?.theme) ? value.theme : 'future',
    size: ['normal', 'large', 'larger'].includes(value?.size) ? value.size : 'normal',
    motion: ['system', 'reduce', 'full'].includes(value?.motion) ? value.motion : 'system'};
}
export function read(storage) {
  try {
    const current = storage.getItem(KEY);
    if (current !== null && current !== undefined) return normalize(JSON.parse(current));
    const legacy = storage.getItem(LEGACY_KEY);
    if (legacy !== null && legacy !== undefined) {
      const previous = normalize(JSON.parse(legacy));
      return {...previous, theme: 'future'};
    }
    return normalize(null);
  } catch (_) { return normalize(null); }
}
export function save(storage, value) {
  try { storage.setItem(KEY, JSON.stringify(normalize(value))); return true; } catch (_) { return false; }
}
export function apply(root, value, dark, systemReducedMotion = false) {
  const prefs = normalize(value);
  root.dataset.theme = prefs.theme === 'system' ? (dark ? 'dark' : 'light') : prefs.theme;
  root.dataset.reading = prefs.size;
  root.dataset.motion = prefs.motion === 'system'
    ? (systemReducedMotion ? 'reduce' : 'full')
    : prefs.motion;
}
