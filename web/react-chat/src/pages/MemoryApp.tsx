import {lazy, Suspense} from 'react';
import {Alert, Button} from 'antd';
import {useSearchParams} from 'react-router-dom';
import {ChatApi} from '../api';
import {useMemoryEngine, memoryEngineLabel} from '../app/MemoryEngineProvider';
import {AppShell, ConsoleNav} from '../components/AppShell';
import {HyMemoryWorkspace} from '../features/memory/HyMemoryWorkspace';

const api = new ChatApi();
const Mechanisms = lazy(() => import('../features/memory/HyMechanismsWorkspace').then(module => ({default: module.HyMechanismsWorkspace})));

export function MemoryApp() {
  const engine = useMemoryEngine();
  const [params] = useSearchParams();
  if (engine.phase !== 'ready' || engine.kind !== 'hy') {
    return <AppShell subtitle="长期记忆" sidebar={<ConsoleNav active="memories"/>}>
      <Alert type="info" showIcon title={memoryEngineLabel(engine)}
        action={engine.phase === 'error' && <Button onClick={engine.refresh}>重新核对引擎</Button>}/>
    </AppShell>;
  }
  if (params.get('view') === 'mechanisms') {
    return <Suspense fallback={<p role="status">正在加载记忆机制…</p>}><Mechanisms/></Suspense>;
  }
  return <HyMemoryWorkspace api={api} method={engine.identity?.method ?? undefined}/>;
}
