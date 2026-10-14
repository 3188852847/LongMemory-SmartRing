import {afterEach, expect, test, vi} from 'vitest';
import {render} from '@testing-library/react';
import {TransitionSurface} from './TransitionSurface';

afterEach(() => {delete document.documentElement.dataset.inputModality; delete document.documentElement.dataset.motion; vi.restoreAllMocks();});

test('快速详情切换取消旧动画并从当前帧续接，卸载清理动画', () => {
  const first = {playState: 'running', cancel: vi.fn()} as unknown as Animation;
  const second = {playState: 'running', cancel: vi.fn()} as unknown as Animation;
  const animate = vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second);
  const {container, rerender, unmount} = render(<TransitionSurface identity="daily">常用</TransitionSurface>);
  Object.defineProperty(container.firstElementChild, 'animate', {value: animate});
  rerender(<TransitionSurface identity="memory">记忆</TransitionSurface>);
  expect(animate).toHaveBeenCalledTimes(1);
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({opacity: '.94', transform: 'matrix(1, 0, 0, 1, 0, 1)'} as CSSStyleDeclaration);
  rerender(<TransitionSurface identity="voice">语音</TransitionSurface>);
  expect(first.cancel).toHaveBeenCalledTimes(1);
  expect(animate.mock.calls[1][0][0]).toEqual({opacity: '.94', transform: 'matrix(1, 0, 0, 1, 0, 1)'});
  expect(container.textContent).toBe('语音');
  unmount(); expect(second.cancel).toHaveBeenCalledTimes(1);
});

test.each(['keyboard', 'reduce'])('%s 偏好下详情立即显示，不调用动画', preference => {
  if (preference === 'keyboard') document.documentElement.dataset.inputModality = 'keyboard';
  else document.documentElement.dataset.motion = 'reduce';
  const {container, rerender} = render(<TransitionSurface identity="daily">常用</TransitionSurface>);
  const animate = vi.fn(); Object.defineProperty(container.firstElementChild, 'animate', {value: animate});
  rerender(<TransitionSurface identity="voice">语音</TransitionSurface>);
  expect(container.textContent).toBe('语音'); expect(animate).not.toHaveBeenCalled();
});
