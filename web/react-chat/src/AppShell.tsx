import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';

type Page = 'device' | 'display' | 'chat' | 'memories' | 'scenarios' | 'personas' | 'settings' | 'experiments';

const NAV_GROUPS: Array<{label: string; items: Array<{
  page: Page; icon: string; label: string; description: string; to: string;
}>}> = [
  {label: '日常使用', items: [
    {page: 'chat', icon: '聊', label: '文字聊天', description: '对话与记忆过程', to: '/chat-react'},
    {page: 'device', icon: '屏', label: '设备状态', description: '连接、快照与基础控制', to: '/device'},
    {page: 'display', icon: '显', label: '圆屏预览', description: '状态、情绪与异常', to: '/display-preview'},
  ]},
  {label: '长期记忆', items: [
    {page: 'memories', icon: 'L1', label: '原始与原子记忆', description: 'L0 来源与 L1 事实', to: '/memories'},
    {page: 'scenarios', icon: 'L2', label: '生活场景', description: 'L2 情境整理', to: '/scenarios'},
    {page: 'personas', icon: 'L3', label: '用户画像', description: 'L3 长期认识', to: '/personas'},
  ]},
  {label: '控制与观察', items: [
    {page: 'settings', icon: '设', label: '设置中心', description: '角色、声音与主动交流', to: '/settings'},
    {page: 'experiments', icon: '验', label: '实验中心', description: '对照运行与结果复核', to: '/experiments-react'},
  ]},
];

function NavItem({item, active}: {item: typeof NAV_GROUPS[number]['items'][number]; active: boolean}) {
  const content = <><span className="nav-icon" aria-hidden="true">{item.icon}</span><span className="nav-copy">
    <span>{item.label}</span><small>{item.description}</small>
  </span></>;
  return active
    ? <div className="console-nav-link active" aria-current="page">{content}</div>
    : <Link className="console-nav-link" aria-label={item.label} to={item.to}>{content}</Link>;
}

/** 控制台各 React 页面共享的外壳；页面只负责自己的业务控件。 */
export function AppShell({subtitle, className = '', sidebar, children}: {
  subtitle: string;
  className?: string;
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return <div className={`shell ${className}`.trim()}>
    <a className="skip-link" href="#main-content">跳到主要内容</a>
    <aside><div className="sidebar-inner">
      <div className="brand-block"><Link aria-label="LongMemory" className="brand" to="/chat-react">
        <span className="brand-mark" aria-hidden="true">LM</span><span className="brand-copy"><strong>LongMemory</strong><small>Companion console</small></span>
      </Link><p>{subtitle}</p></div>
      {sidebar}
      <div className="sidebar-footer"><i aria-hidden="true"/>本机个人空间</div>
    </div></aside>
    <main id="main-content"><div className="shell-content">{children}</div></main>
  </div>;
}

/** React 内部页面使用客户端路由；原版入口只保留为迁移期回退。 */
export function ConsoleNav({active, legacyPath}: {active: Page; legacyPath: string}) {
  return <>
    <nav className="console-nav" aria-label="控制台导航">
      {NAV_GROUPS.map(group => <section className="nav-group" key={group.label}>
        <h2>{group.label}</h2>
        {group.items.map(item => <NavItem key={item.page} item={item} active={active === item.page}/>)}
      </section>)}
    </nav>
    <details className="legacy-entry"><summary>兼容入口</summary>
      <a href={legacyPath}>打开原版页面</a><p>仅用于迁移期排障，日常操作请使用上方新版页面。</p>
    </details>
  </>;
}
