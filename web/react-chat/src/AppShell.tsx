import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';

type Page = 'device' | 'chat' | 'memories' | 'scenarios' | 'personas' | 'settings' | 'experiments';

const NAV_GROUPS: Array<{label: string; items: Array<{
  page: Page; label: string; description: string; to: string;
}>}> = [
  {label: '日常使用', items: [
    {page: 'chat', label: '文字聊天', description: '对话与记忆过程', to: '/chat-react'},
    {page: 'device', label: '设备状态', description: '圆屏连接与音量', to: '/device'},
  ]},
  {label: '长期记忆', items: [
    {page: 'memories', label: '原始与原子记忆', description: 'L0 来源与 L1 事实', to: '/memories'},
    {page: 'scenarios', label: '生活场景', description: 'L2 情境整理', to: '/scenarios'},
    {page: 'personas', label: '用户画像', description: 'L3 长期认识', to: '/personas'},
  ]},
  {label: '控制与观察', items: [
    {page: 'settings', label: '设置中心', description: '角色、声音与主动交流', to: '/settings'},
    {page: 'experiments', label: '实验中心', description: '对照运行与结果复核', to: '/experiments-react'},
  ]},
];

/** 控制台各 React 页面共享的外壳；页面只负责自己的业务控件。 */
export function AppShell({subtitle, className = '', sidebar, children}: {
  subtitle: string;
  className?: string;
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return <div className={`shell ${className}`.trim()}>
    <aside><div className="sidebar-inner">
      <div className="brand-block"><span>个人陪伴控制台</span><Link className="brand" to="/chat-react">LongMemory</Link><p>{subtitle}</p></div>
      {sidebar}
    </div></aside>
    <main>{children}</main>
  </div>;
}

/** React 内部页面使用客户端路由；原版入口只保留为迁移期回退。 */
export function ConsoleNav({active, legacyPath}: {active: Page; legacyPath: string}) {
  return <>
    <nav className="console-nav" aria-label="控制台导航">
      {NAV_GROUPS.map(group => <section className="nav-group" key={group.label}>
        <h2>{group.label}</h2>
        {group.items.map(item => active === item.page
          ? <div className="console-nav-link active" aria-current="page" key={item.page}>
              <span>{item.label}</span><small>{item.description}</small>
            </div>
          : <Link className="console-nav-link" aria-label={item.label} to={item.to} key={item.page}>
              <span>{item.label}</span><small>{item.description}</small>
            </Link>)}
      </section>)}
    </nav>
    <details className="legacy-entry"><summary>兼容入口</summary>
      <a href={legacyPath}>打开原版页面</a><p>仅用于迁移期排障，日常操作请使用上方新版页面。</p>
    </details>
  </>;
}
