import type {HTMLAttributes, ReactNode} from 'react';

/** 两个入口共用视觉构件；颜色跟随 AppearanceProvider，不接管业务状态。 */
export function SciFiSurface({children, className = '', ...props}: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`scifi-surface ${className}`.trim()}>{children}</div>;
}

export function StatusIndicator({tone = 'quiet', children}: {
  tone?: 'quiet' | 'good' | 'busy' | 'warning' | 'bad'; children: ReactNode;
}) {
  return <span className={`shared-status tone-${tone}`}><i aria-hidden="true"/>{children}</span>;
}

export function OrbitMark({className = ''}: {className?: string}) {
  return <svg className={`orbit-mark ${className}`} viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <circle cx="24" cy="24" r="17" stroke="currentColor" strokeWidth="1.3"/>
    <path d="M7 24h34M24 7v34" stroke="currentColor" strokeOpacity=".35"/>
    <circle cx="24" cy="24" r="8" stroke="currentColor" strokeWidth="1.3"/>
    <circle cx="37" cy="13" r="3" fill="currentColor"/>
  </svg>;
}
