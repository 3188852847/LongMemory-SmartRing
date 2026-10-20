import {createContext, useCallback, useContext, useEffect, useId, useMemo, useState, type ReactNode} from 'react';
import {useBlocker} from 'react-router-dom';

type Register = (id: string, message?: string) => void;
const DraftContext = createContext<Register | null>(null);

/** 草稿仍由原组件管理；此处只登记离页保护，不保存正文或改变业务写入。 */
export function UnsavedChangesProvider({children}: {children: ReactNode}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const register = useCallback<Register>((id, message) => setDrafts(current => {
    if (current[id] === message) return current;
    const next = {...current};
    if (message) next[id] = message; else delete next[id];
    return next;
  }), []);
  const dirty = Object.keys(drafts).length > 0;
  // 分类切换保留原组件，允许继续；跨页面包括浏览器前进/返回都经过路由护栏。
  const shouldBlock = useCallback(({currentLocation, nextLocation}: {
    currentLocation: {pathname: string;search:string}; nextLocation: {pathname: string;search:string};
  }) => {
    const mechanisms=(location:{pathname:string;search:string})=>location.pathname==='/memories'&&new URLSearchParams(location.search).get('view')==='mechanisms';
    return dirty&&(currentLocation.pathname!==nextLocation.pathname||mechanisms(currentLocation)!==mechanisms(nextLocation));
  }, [dirty]);
  const blocker = useBlocker(shouldBlock);
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (window.confirm(`${Object.values(drafts).join('\n')}\n离开会丢弃编辑，继续吗？`)) blocker.proceed();
    else blocker.reset();
  }, [blocker, drafts]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = '';};
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  return <DraftContext.Provider value={register}>{children}</DraftContext.Provider>;
}

/** 测试单独挂载页面时也保留原有刷新保护；正式装配中使用统一路由保护。 */
export function useUnsavedChanges(dirty: boolean, message: string) {
  const register = useContext(DraftContext);
  const id = useId();
  const warning = useMemo(() => dirty ? message : undefined, [dirty, message]);
  useEffect(() => {
    if (register) {register(id, warning); return () => register(id);}
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = '';};
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [register, id, warning, dirty]);
}
