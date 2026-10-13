import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {theme} from 'antd';
import {KEY} from '../../../assets/appearance.mjs';
import {AppearanceProvider, useAppearance} from './AppearanceProvider';

function MotionProbe() {
  const {token} = theme.useToken();
  const {prefs, update} = useAppearance();
  return <><span role="status">{token.motion ? '允许组件运动' : '减少组件运动'}</span>
    <button onClick={() => update({...prefs, motion: 'reduce'})}>减少动态效果</button></>;
}

afterEach(() => {localStorage.clear(); vi.unstubAllGlobals();});

describe('共享主题的组件库运动偏好', () => {
  test.each([
    ['system', false, '允许组件运动'],
    ['system', true, '减少组件运动'],
    ['reduce', false, '减少组件运动'],
    ['full', true, '允许组件运动'],
  ] as const)('%s，系统减少动态为 %s：%s', (motion, systemReduced, expected) => {
    localStorage.setItem(KEY, JSON.stringify({motion}));
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)' && systemReduced,
      media: query, addEventListener() {}, removeEventListener() {},
    }));
    render(<AppearanceProvider><MotionProbe/></AppearanceProvider>);
    expect(screen.getByRole('status').textContent).toBe(expected);
    expect(document.documentElement.dataset.motion).toBe(expected === '减少组件运动' ? 'reduce' : 'full');
  });

  test('用户切换后同步更新组件库 token 和页面偏好，涵盖 Portal 所用主题', () => {
    localStorage.setItem(KEY, JSON.stringify({motion: 'full'}));
    render(<AppearanceProvider><MotionProbe/></AppearanceProvider>);
    expect(screen.getByRole('status').textContent).toBe('允许组件运动');
    fireEvent.click(screen.getByRole('button', {name: '减少动态效果'}));
    expect(screen.getByRole('status').textContent).toBe('减少组件运动');
    expect(document.documentElement.dataset.motion).toBe('reduce');
  });
});
