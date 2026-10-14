import {useEffect, useState} from 'react';

export const AMBIENT_KEY = 'longmemory:ambient-motion:v1';
const AMBIENT_EVENT = 'longmemory:ambient-motion-changed';

function readEnabled() {
  try {return localStorage.getItem(AMBIENT_KEY) !== 'off';} catch {return true;}
}

/** 独立的显示偏好，不进入启动配置、个人记忆或外观 v3 的持久化格式。 */
function useAmbientPreference() {
  const [enabled, setEnabled] = useState(readEnabled);
  useEffect(() => {
    const sync = () => setEnabled(readEnabled());
    const onPreference = (event: Event) => {
      const value = (event as CustomEvent<boolean>).detail;
      if (typeof value === 'boolean') setEnabled(value); else sync();
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === AMBIENT_KEY || event.key === null) sync();
    };
    window.addEventListener(AMBIENT_EVENT, onPreference);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(AMBIENT_EVENT, onPreference);
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  function toggle() {
    const next = !enabled;
    setEnabled(next);
    document.documentElement.dataset.ambient = next ? 'on' : 'off';
    try {
      localStorage.setItem(AMBIENT_KEY, next ? 'on' : 'off');
    } catch { /* 存储不可用时，本次页面仍可立即关闭动态。 */ }
    window.dispatchEvent(new CustomEvent(AMBIENT_EVENT, {detail: next}));
  }
  return {enabled, toggle};
}

/** 固定的边缘光轨只是环境装饰；没有进度、数字、遥测或可聚焦节点。 */
export function DigitalAtmosphere({launcher = false}: {launcher?: boolean}) {
  const {enabled} = useAmbientPreference();
  useEffect(() => {
    document.documentElement.dataset.ambient = enabled ? 'on' : 'off';
    const onVisibility = () => {
      document.documentElement.dataset.pageVisibility = document.hidden ? 'hidden' : 'visible';
    };
    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [enabled]);
  return <div className={`digital-atmosphere${launcher ? ' atmosphere-launcher' : ''}`} aria-hidden="true" inert>
    <div className="atmosphere-track track-top"><i/></div>
    <div className="atmosphere-track track-side"><i/></div>
    <div className="atmosphere-ring"><i/></div>
  </div>;
}

/** 真正的控制与装饰分开，网页可用键盘访问；关闭后保留静态光轨。 */
export function AmbientMotionToggle({floating = false}: {floating?: boolean}) {
  const {enabled, toggle} = useAmbientPreference();
  return <button type="button" className={`ambient-motion-toggle${floating ? ' ambient-motion-floating' : ''}`}
    aria-pressed={enabled} aria-label="持续光效" title="开关持续光效；减少动画设置始终优先" onClick={toggle}>
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="10" cy="10" r="6" stroke="currentColor"/>
      <path d="M10 1v3m0 12v3M1 10h3m12 0h3" stroke="currentColor"/></svg>
    <span>光效{enabled ? '开' : '关'}</span>
  </button>;
}
