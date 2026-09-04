// 仅保存本浏览器的显示偏好，不保存聊天正文，也不写入长期记忆。
export const KEY = 'longmemory:chat-appearance:v1';
export function normalize(value) {
  return {theme: ['system', 'light', 'dark'].includes(value?.theme) ? value.theme : 'system',
    size: ['normal', 'large', 'larger'].includes(value?.size) ? value.size : 'normal'};
}
export function read(storage) {
  try { return normalize(JSON.parse(storage.getItem(KEY))); } catch (_) { return normalize(null); }
}
export function save(storage, value) {
  try { storage.setItem(KEY, JSON.stringify(normalize(value))); return true; } catch (_) { return false; }
}
export function apply(root, value, dark) {
  const prefs = normalize(value);
  root.dataset.theme = prefs.theme === 'system' ? (dark ? 'dark' : 'light') : prefs.theme;
  root.dataset.reading = prefs.size;
}
