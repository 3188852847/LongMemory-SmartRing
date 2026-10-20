import {useEffect, useId, useState, type ReactNode} from 'react';
import {Link, useLocation} from 'react-router-dom';
import {OrbitMark, StatusIndicator} from './SciFiSurface';
import {AmbientMotionToggle} from './DigitalAtmosphere';
import {useMemoryEngine, memoryEngineLabel} from '../app/MemoryEngineProvider';

type Page = 'overview' | 'device' | 'display' | 'chat' | 'memories' | 'mechanisms' | 'quality' | 'scenarios' | 'personas' | 'settings' | 'experiments';

const NAV_GROUPS: Array<{label: string; items: Array<{
  page: Page; icon: string; label: string; description: string; to: string;
}>}> = [
  {label: '日常使用', items: [
    {page: 'overview', icon: '总', label: '系统总览', description: '服务、模型、记忆与圆屏', to: '/overview'},
    {page: 'chat', icon: '聊', label: '文字聊天', description: '对话与记忆过程', to: '/chat-react'},
    {page: 'device', icon: '屏', label: '设备状态', description: '连接、快照与基础控制', to: '/device'},
    {page: 'display', icon: '显', label: '圆屏预览', description: '状态、情绪与异常', to: '/display-preview'},
  ]},
  {label: '长期记忆', items: [
    {page: 'memories', icon: '记', label: '原话与事实', description: '从对话查来源、纠正事实', to: '/memories'},
    {page: 'quality', icon: '质', label: '记忆质量', description: '跨日问题样本与诊断', to: '/memory-quality'},
    {page: 'scenarios', icon: '景', label: '生活场景', description: '相关事实组成的经历', to: '/scenarios'},
    {page: 'personas', icon: '像', label: '用户画像', description: '有来源的长期认识', to: '/personas'},
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
  return <Link className={`console-nav-link${active ? ' active' : ''}`} aria-current={active ? 'page' : undefined}
    aria-label={item.label} to={item.to}>{content}</Link>;
}

/** 控制台各 React 页面共享的外壳；页面只负责自己的业务控件。 */
export function AppShell({subtitle, className = '', layout = 'page', sidebar, children}: {
  subtitle: string;
  className?: string;
  layout?: 'page' | 'workspace';
  sidebar: ReactNode;
  children: ReactNode;
}) {
  const [navOpen, setNavOpen] = useState(false);
  const navigationId = useId();
  const location = useLocation();
  // 保留普通页面的滚动方式；仅聊天显式请求视口内工作区。
  useEffect(() => setNavOpen(false), [location.pathname, location.search]);
  return <div className={`shell workspace-shell layout-${layout} ${className}`.trim()}>
    <a className="skip-link" href="#main-content">跳到主要内容</a>
    <aside className={`shell-sidebar${navOpen ? ' nav-open' : ''}`}><div className="sidebar-inner">
      <div className="brand-block"><Link aria-label="智慧圆屏" className="brand" to="/overview">
        <OrbitMark/><span className="brand-copy"><strong>智慧圆屏</strong><small>个人陪伴控制台</small></span>
      </Link><p>{subtitle}</p></div>
      <button type="button" className="shell-nav-toggle" aria-expanded={navOpen} aria-controls={navigationId}
        onClick={() => setNavOpen(open => !open)}>{navOpen ? '收起导航' : '展开导航'}</button>
      <div id={navigationId} className="shell-navigation" onClick={event => {
        if ((event.target as HTMLElement).closest('a')) setNavOpen(false);
      }} onKeyDown={event => {
        if (event.key === 'Escape') {setNavOpen(false); event.currentTarget.parentElement?.querySelector<HTMLButtonElement>('.shell-nav-toggle')?.focus();}
      }}>{sidebar}</div>
      <div className="sidebar-footer"><AmbientMotionToggle/><StatusIndicator>本机个人空间</StatusIndicator></div>
    </div></aside>
    <main id="main-content" tabIndex={-1}><div className="shell-content">{children}</div></main>
  </div>;
}

/** React 内部页面使用客户端路由；原版入口只保留为迁移期回退。 */
export function ConsoleNav({active, legacyPath}: {active: Page; legacyPath: string}) {
  const engine=useMemoryEngine();
  const location=useLocation();
  const selected=location.pathname==='/memories'&&new URLSearchParams(location.search).get('view')==='mechanisms'?'mechanisms':active;
  const memoryItems=engine.kind==='hy'?[
    {page:'memories' as Page,icon:'记',label:'我的记忆',description:'内容、来源与明确纠正',to:'/memories'},
    {page:'mechanisms' as Page,icon:'理',label:'记忆机制',description:'分层、运行路径与证据',to:'/memories?view=mechanisms'},
  ]:engine.kind==='legacy'?NAV_GROUPS[1].items:[
    {page:'memories' as Page,icon:'记',label:'记忆管理',description:memoryEngineLabel(engine),to:'/memories'},
    {page:'mechanisms' as Page,icon:'理',label:'记忆机制',description:'身份确认后读取机制声明',to:'/memories?view=mechanisms'},
  ];
  const groups=NAV_GROUPS.map(group=>group.label==='长期记忆'?{...group,items:memoryItems}:group);
  return <>
    <nav className="console-nav" aria-label="控制台导航">
      {groups.map(group => <section className="nav-group" key={group.label}>
        <h2>{group.label}</h2>
        {group.items.map(item => <NavItem key={item.page} item={item} active={selected === item.page}/>)}
      </section>)}
    </nav>
    {engine.phase!=='ready'&&<div className="memory-engine-notice" role="status"><p>{engine.phase==='error'?(engine.issue==='busy'?'引擎暂忙，未取得新身份；保留未知或上次确认的入口。':engine.identity?'记忆身份核对失败；保留上次确认的入口。':'未能确认当前引擎，入口保持中立。'):'正在确认引擎，其他功能可继续使用。'}</p>{engine.phase==='error'&&<button type="button" disabled={engine.refreshing} onClick={engine.refresh}>重新核对引擎</button>}</div>}
    {engine.kind==='hy'?<details className="legacy-entry memory-term-map"><summary>关于这份记忆</summary><p>Hy 从独立新库积累。Hy L0 是基本信息；平台原话是独立来源账本，不是 Hy L0。</p><p>机制页区分 SDK 支持、当前接入和实际证据。旧库保留。</p></details>:engine.kind==='legacy'?<details className="legacy-entry memory-term-map"><summary>记忆名称与研究编号</summary><p>原话（L0）：保存的对话来源。事实（L1）：从原话提取的记忆。场景（L2）：相关事实组成的经历。画像（L3）：有来源的长期认识。</p></details>:null}
    {engine.kind==='legacy'&&<details className="legacy-entry"><summary>兼容入口</summary>
      <a href={legacyPath}>打开原版页面</a><p>仅用于迁移期排障，日常操作请使用上方新版页面。</p>
    </details>}
  </>;
}
