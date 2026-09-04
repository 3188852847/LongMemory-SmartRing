import {read, save, apply, normalize, KEY} from '/assets/appearance.mjs';
const theme = document.getElementById('appearance-theme');
const size = document.getElementById('appearance-size');
const notice = document.getElementById('appearance-notice');
const media = matchMedia('(prefers-color-scheme: dark)');
let storage;
try { storage = localStorage; } catch (_) { /* 隐私模式禁用存储时只在本页生效。 */ }
let prefs = read(storage);
function render() {
  apply(document.documentElement, prefs, media.matches);
  theme.value = prefs.theme; size.value = prefs.size;
}
function update() {
  prefs = normalize({theme: theme.value, size: size.value});
  render();
  notice.textContent = save(storage, prefs) ? '已保存到此浏览器；不影响圆屏、声音或记忆。' : '本页已生效，但浏览器不允许保存设置。';
}
theme.addEventListener('change', update);
size.addEventListener('change', update);
document.getElementById('appearance-reset').addEventListener('click', () => {
  theme.value = 'system'; size.value = 'normal'; update();
});
media.addEventListener('change', render);
window.addEventListener('storage', event => {
  if (event.key === KEY || event.key === null) { prefs = read(storage); render(); }
});
render();
