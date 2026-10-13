import {useId, useLayoutEffect, useRef, type ReactNode} from 'react';
import {useLocation, useSearchParams} from 'react-router-dom';
import './data-workspace.css';

// 同一渲染坐标的各参数共用待提交快照，避免一次事件的多项更新互相覆盖。
// WeakMap 跟随路由对象释放；实际正文和业务草稿始终留在原组件中。
const pendingCoordinates = new WeakMap<object, URLSearchParams>();

/** 只保存浏览坐标，不保存详情正文、模型结果或未保存的业务草稿。 */
export function useWorkspaceParam(key:string, fallback:string, allowed?:readonly string[]) {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const raw = params.get(key);
  const value = raw !== null && raw.length <= 200 && !/[\u0000-\u001f\u007f]/.test(raw)
    && (!allowed || allowed.includes(raw)) ? raw : fallback;
  pendingCoordinates.set(location, new URLSearchParams(params));
  const latest = useRef(location);
  latest.current = location;
  function setValue(next:string, replace=true) {
    // 同一事件可更新筛选、分页与选中项；使用最新快照避免互相覆盖。
    const updated = new URLSearchParams(pendingCoordinates.get(latest.current) ?? params);
    if (next === fallback) updated.delete(key); else updated.set(key, next);
    pendingCoordinates.set(latest.current, updated);
    setParams(updated, {replace});
  }
  return [value, setValue] as const;
}

type Task = {key:string; label:string; children:ReactNode};
const scrollPositions = new Map<string, number>();

/** 任务面板保留挂载，切换不丢失筛选、详情、草稿或各自的浏览位置。 */
export function DataWorkspace({label, items, activeKey, onChange}:{label:string; items:Task[]; activeKey:string; onChange:(key:string,replace?:boolean)=>void}) {
  const id = useId();
  const location = useLocation();
  return <section className="data-workspace" aria-label={label}>
    <nav className="data-workspace-nav" aria-label={`${label}任务`}>
      {items.map(item=><button type="button" key={item.key} aria-pressed={activeKey===item.key}
        aria-controls={`${id}-${item.key}`} onClick={()=>onChange(item.key,false)}>{item.label}</button>)}
    </nav>
    {items.map(item=><WorkspacePanel key={item.key} id={`${id}-${item.key}`} label={item.label}
      positionKey={`${location.pathname}:${item.key}`} active={activeKey===item.key}>{item.children}</WorkspacePanel>)}
  </section>;
}

function WorkspacePanel({id,label,positionKey,active,children}:{id:string; label:string; positionKey:string; active:boolean; children:ReactNode}) {
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(()=>{
    const panel = ref.current;
    if (!panel || !active) return;
    panel.scrollTop = scrollPositions.get(positionKey) ?? 0;
  },[active,positionKey]);
  return <section ref={ref} id={id} aria-label={label} hidden={!active} className="data-workspace-panel"
    tabIndex={active?0:-1} onScroll={event=>scrollPositions.set(positionKey,event.currentTarget.scrollTop)}>{children}</section>;
}
