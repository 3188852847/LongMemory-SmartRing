type CoreState = 'unknown' | 'stopped' | 'starting' | 'ready' | 'stopping' | 'failed';

/** 环形状态核心复用同一光效规则。仅表达真实服务状态，不代表设备聆听或音频音量。 */
export function StateCore({state}: {state: CoreState}) {
  return <div className={`state-core launcher-orb core-${state}`} data-state={state} aria-hidden="true">
    <div className="orb-grid"/><div className="orb-orbit orbit-one"/><div className="orb-orbit orbit-two"/>
    <svg className="orb-symbol" viewBox="0 0 100 100" fill="none">
      {state === 'ready' ? <path d="m29 50 14 14 29-30" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
        : state === 'failed' ? <><path d="M50 26v30" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/><circle cx="50" cy="69" r="2.5" fill="currentColor"/></>
        : <path d="M50 18v36M30 28a31 31 0 1 0 40 0" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>}
    </svg>
    <div className="orb-signal"/>
    {(state === 'starting' || state === 'stopping') && <div className="core-pulse"><i/><i/><i/></div>}
  </div>;
}
