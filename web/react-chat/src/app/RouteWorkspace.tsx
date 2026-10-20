import {useEffect, useLayoutEffect, useRef} from 'react';
import {Outlet, ScrollRestoration, useLocation, useNavigationType} from 'react-router-dom';
import {UnsavedChangesProvider} from './UnsavedChanges';
import {MemoryEngineProvider} from './MemoryEngineProvider';

// 与 ScrollRestoration 共用其显式存储键，只读坐标，不增加正文或持久个人数据。
const SCROLL_STORAGE_KEY='react-router-scroll-positions';
function savedPositions() {
  try {
    const saved:unknown=JSON.parse(sessionStorage.getItem(SCROLL_STORAGE_KEY)??'{}');
    if(!saved||typeof saved!=='object'||Array.isArray(saved))return new Map<string,number>();
    return new Map(Object.entries(saved).filter((entry):entry is [string,number]=>typeof entry[1]==='number'&&Number.isFinite(entry[1])&&entry[1]>=0).slice(-200));
  }catch{return new Map<string,number>();}
}

/** 普通新页面回到入口；历史返回恢复文档滚动，消息/数据面板仍由各自组件管理。 */
export function RouteWorkspace() {
  const location = useLocation();
  const navigation = useNavigationType();
  const previousPath = useRef(location.pathname);
  const positions = useRef(savedPositions());
  const activeKey = useRef(location.key);
  const lastY = useRef(window.scrollY);
  useEffect(() => {
    const observe = () => {lastY.current = window.scrollY;};
    window.addEventListener('scroll', observe, {passive:true});
    return () => window.removeEventListener('scroll', observe);
  }, []);
  useLayoutEffect(() => {
    if(activeKey.current!==location.key)positions.current.set(activeKey.current, lastY.current);
    while (positions.current.size > 200) positions.current.delete(positions.current.keys().next().value!);
    const target = positions.current.get(location.key);
    activeKey.current = location.key;
    lastY.current = window.scrollY;
    if (navigation !== 'POP' || !target) return;
    // 首次恢复时懒页面/列表可能尚短，浏览器把旧位置夹成 0；等真实布局够高再恢复一次。
    // 只缓存坐标，且用户开始滚动/操作后立即取消，不能继续抢回阅读位置。
    let active = true;
    const restore = () => {
      if (!active || document.documentElement.scrollHeight - innerHeight < target - 1) return;
      window.scrollTo(0, target);lastY.current = window.scrollY;active = false;
    };
    restore();
    if (!active) return;
    const observer = new ResizeObserver(restore);
    observer.observe(document.body);observer.observe(document.documentElement);
    const cancel = () => {active = false;observer.disconnect();};
    window.addEventListener('wheel', cancel, {passive:true});
    window.addEventListener('pointerdown', cancel, true);
    window.addEventListener('keydown', cancel, true);
    return () => {cancel();window.removeEventListener('wheel', cancel);window.removeEventListener('pointerdown', cancel, true);window.removeEventListener('keydown', cancel, true);};
  }, [location.key, navigation]);
  useEffect(() => {
    if (previousPath.current === location.pathname) return;
    previousPath.current = location.pathname;
    if (navigation === 'POP') return;
    // 懒加载可能晚于路由变更，等待 main 出现；只处理一次，不抢夺输入焦点。
    const focusMain = () => {
      const main = document.getElementById('main-content');
      if (!main) return false;
      main.focus({preventScroll: true});
      return true;
    };
    if (focusMain()) return;
    const observer = new MutationObserver(() => {if (focusMain()) observer.disconnect();});
    observer.observe(document.body, {childList: true, subtree: true});
    return () => observer.disconnect();
  }, [location.pathname, navigation]);
  const nonce = document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content;
  return <MemoryEngineProvider><UnsavedChangesProvider><Outlet/><ScrollRestoration nonce={nonce} storageKey={SCROLL_STORAGE_KEY}/></UnsavedChangesProvider></MemoryEngineProvider>;
}
