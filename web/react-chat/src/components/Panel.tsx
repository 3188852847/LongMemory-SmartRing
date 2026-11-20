import type {ReactNode} from 'react';
import {Card} from '@astryxdesign/core/Card';
import {Heading} from '@astryxdesign/core/Heading';

export function Panel({title, extra, size, className, children}: {
  title?: ReactNode; extra?: ReactNode; size?: 'small'; className?: string; children: ReactNode;
}) {
  return <Card className={['companion-panel', className].filter(Boolean).join(' ')} padding={0}>
    {(title || extra) && <div className="companion-panel-head"><div className="companion-panel-head-wrapper">
      {title && <Heading level={2} className="companion-panel-head-title">{title}</Heading>}
      {extra && <div className="companion-panel-extra">{extra}</div>}
    </div></div>}
    <div className="companion-panel-body" data-compact={size === 'small' || undefined}>{children}</div>
  </Card>;
}
