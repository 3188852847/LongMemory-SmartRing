import type {ReactNode} from 'react';
import {SciFiSurface} from './SciFiSurface';

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  description?: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
};

/**
 * 所有控制台页面共用同一标题层级，让用户先判断“我在哪、这里做什么”，
 * 再接触数据库路径、刷新按钮等次要状态，避免研究术语先于日常任务出现。
 */
export function PageHeader({eyebrow, title, description, meta, action}: PageHeaderProps) {
  return <header className="page-header">
    <div className="page-heading">
      <p className="page-kicker">{eyebrow}</p>
      <h1>{title}</h1>
      {description && <p className="page-description">{description}</p>}
      {meta && <SciFiSurface className="page-meta">{meta}</SciFiSurface>}
    </div>
    {action && <div className="page-action">{action}</div>}
  </header>;
}
