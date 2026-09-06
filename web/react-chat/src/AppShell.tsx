import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';

type Page = 'device' | 'chat' | 'memories' | 'scenarios' | 'settings' | 'experiments';

/** 控制台各 React 页面共享的外壳；页面只负责自己的业务控件。 */
export function AppShell({subtitle, className = '', sidebar, children}: {
  subtitle: string;
  className?: string;
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return <div className={`shell ${className}`.trim()}>
    <aside><Link className="brand" to="/chat-react">LongMemory</Link><p>{subtitle}</p>{sidebar}</aside>
    <main>{children}</main>
  </div>;
}

/** React 内部页面使用客户端路由；原版入口只保留为迁移期回退。 */
export function ConsoleNav({active, legacyPath}: {active: Page; legacyPath: string}) {
  return <nav aria-label="控制台导航">
    {active === 'device' ? <strong>设备与状态</strong> : <Link to="/device">设备与状态</Link>}
    {active === 'chat' ? <strong>文字聊天</strong> : <Link to="/chat-react">文字聊天</Link>}
    {active === 'memories' ? <strong>记忆管理</strong> : <Link to="/memories">记忆管理</Link>}
    {active === 'scenarios' ? <strong>生活场景</strong> : <Link to="/scenarios">生活场景</Link>}
    {active === 'settings' ? <strong>个性化设置</strong> : <Link to="/settings">个性化设置</Link>}
    {active === 'experiments' ? <strong>实验中心</strong> : <Link to="/experiments-react">实验中心</Link>}
    <a href={legacyPath}>返回原版页面</a>
  </nav>;
}
