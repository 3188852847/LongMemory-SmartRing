import {type HTMLAttributes, useEffect, useLayoutEffect, useRef} from 'react';

/** 只桥接偶发详情替换，不等待动画才更新内容；快速切换从当前帧继续。 */
export function TransitionSurface({identity, children, className = '', ...props}: HTMLAttributes<HTMLDivElement> & {identity: string}) {
  const node = useRef<HTMLDivElement>(null);
  const animation = useRef<Animation | null>(null);
  const previous = useRef(identity);
  useLayoutEffect(() => {
    if (previous.current === identity) return;
    previous.current = identity;
    const element = node.current;
    const root = document.documentElement;
    // 高频键盘导航直接更新；系统减少动画也有最终保护，不依赖 Provider 初始化时序。
    const reduce = root.dataset.motion === 'reduce' || matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!element || typeof element.animate !== 'function' || reduce || root.dataset.inputModality === 'keyboard') {
      animation.current?.cancel(); animation.current = null; return;
    }
    const running = animation.current?.playState === 'running';
    const current = running ? getComputedStyle(element) : null;
    const from = {opacity: current?.opacity ?? '.82', transform: current?.transform ?? 'translateY(3px)'};
    animation.current?.cancel();
    animation.current = element.animate([from, {opacity: '1', transform: 'translateY(0)'}],
      {duration: 160, easing: 'cubic-bezier(0.23, 1, 0.32, 1)'});
  }, [identity]);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const stopWhenNeeded = () => {
      if (media.matches || document.documentElement.dataset.motion === 'reduce' || document.documentElement.dataset.inputModality === 'keyboard' || document.hidden) {
        animation.current?.cancel(); animation.current = null;
      }
    };
    const observer = new MutationObserver(stopWhenNeeded);
    observer.observe(document.documentElement, {attributes: true, attributeFilter: ['data-motion', 'data-input-modality']});
    media.addEventListener('change', stopWhenNeeded);
    document.addEventListener('visibilitychange', stopWhenNeeded);
    return () => {
      observer.disconnect(); media.removeEventListener('change', stopWhenNeeded);
      document.removeEventListener('visibilitychange', stopWhenNeeded); animation.current?.cancel();
    };
  }, []);
  return <div {...props} ref={node} className={`transition-surface ${className}`.trim()}>{children}</div>;
}
