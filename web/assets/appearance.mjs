// 仅保存本浏览器的显示偏好，不保存聊天正文，也不写入长期记忆。
export const KEY = 'longmemory:chat-appearance:v3';
export const LEGACY_KEY = 'longmemory:chat-appearance:v2';
export const OLDEST_LEGACY_KEY = 'longmemory:chat-appearance:v1';
export function normalize(value) {
  return {theme: ['system', 'light', 'dark', 'future'].includes(value?.theme) ? value.theme : 'future',
    size: ['normal', 'large', 'larger'].includes(value?.size) ? value.size : 'normal',
    motion: ['system', 'reduce', 'full'].includes(value?.motion) ? value.motion : 'system',
    density: ['comfortable', 'compact'].includes(value?.density) ? value.density : 'comfortable',
    chatWidth: ['focused', 'wide'].includes(value?.chatWidth) ? value.chatWidth : 'focused'};
}
export function read(storage) {
  try {
    const current = storage.getItem(KEY);
    if (current !== null && current !== undefined) return normalize(JSON.parse(current));
    const legacy = storage.getItem(LEGACY_KEY);
    if (legacy !== null && legacy !== undefined) return normalize(JSON.parse(legacy));
    const oldest = storage.getItem(OLDEST_LEGACY_KEY);
    if (oldest !== null && oldest !== undefined) {
      const previous = normalize(JSON.parse(oldest));
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
  root.dataset.density = prefs.density;
  root.dataset.chatWidth = prefs.chatWidth;
  root.dataset.motion = prefs.motion === 'system'
    ? (systemReducedMotion ? 'reduce' : 'full')
    : prefs.motion;
}
