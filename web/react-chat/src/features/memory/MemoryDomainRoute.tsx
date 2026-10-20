import type {ReactNode} from 'react';
import {Navigate} from 'react-router-dom';
import {Alert, Button} from 'antd';
import {useMemoryEngine} from '../../app/MemoryEngineProvider';
import {AppShell, ConsoleNav} from '../../components/AppShell';

/** 旧记忆书签在新引擎中进入对应任务；先核对后端，避免挂载旧页并请求旧库。 */
export function MemoryDomainRoute({legacy,view}:{legacy:ReactNode;view:'profile'|'activity'|'items'}) {
  const engine=useMemoryEngine();
  if(engine.phase==='ready') {
    if(engine.kind==='legacy')return legacy;
    return <Navigate to={`/memories?view=${view}`} replace/>;
  }
  return <AppShell subtitle="核对当前记忆引擎" sidebar={<ConsoleNav active="memories" legacyPath="/memories-legacy"/>}>
    <Alert type={engine.phase==='error'?'error':'info'} title={engine.phase==='error'?'尚未确认当前记忆引擎':'正在核对当前记忆引擎…'}
      description="确认后进入对应记忆任务。其他页面可继续使用。"
      action={engine.phase==='error'?<Button onClick={engine.refresh} loading={engine.refreshing}>重新核对</Button>:undefined}/>
  </AppShell>;
}
