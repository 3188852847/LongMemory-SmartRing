import {afterEach, describe, expect, test, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {AMBIENT_KEY, AmbientMotionToggle, DigitalAtmosphere} from './DigitalAtmosphere';

afterEach(() => {localStorage.clear(); delete document.documentElement.dataset.ambient; vi.restoreAllMocks();});

describe('独立环境光效偏好', () => {
  test('节点全部为无焦点装饰，开关同步且只写浏览器显示偏好', () => {
    const {container} = render(<><DigitalAtmosphere/><AmbientMotionToggle/><AmbientMotionToggle/></>);
    const environment = container.querySelector('.digital-atmosphere')!;
    expect(environment.getAttribute('aria-hidden')).toBe('true');
    expect(environment.hasAttribute('inert')).toBe(true);
    expect(environment.querySelector('button,input,a,[tabindex]')).toBeNull();
    const controls = screen.getAllByRole('button', {name: '持续光效'});
    fireEvent.click(controls[0]);
    expect(controls.every(control => control.getAttribute('aria-pressed') === 'false')).toBe(true);
    expect(document.documentElement.dataset.ambient).toBe('off');
    expect(localStorage.length).toBe(1);
    expect(localStorage.getItem(AMBIENT_KEY)).toBe('off');
  });
  test('存储不可用仍可关闭当前页面光效', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw new Error('blocked');});
    render(<><DigitalAtmosphere/><AmbientMotionToggle/></>);
    fireEvent.click(screen.getByRole('button', {name: '持续光效'}));
    expect(document.documentElement.dataset.ambient).toBe('off');
    expect(screen.getByRole('button', {name: '持续光效'}).getAttribute('aria-pressed')).toBe('false');
  });
  test('跨页面存储变化与隐藏事件只改变视觉状态', () => {
    render(<><DigitalAtmosphere/><AmbientMotionToggle/></>);
    localStorage.setItem(AMBIENT_KEY, 'off');
    fireEvent(window, new StorageEvent('storage', {key: AMBIENT_KEY}));
    expect(document.documentElement.dataset.ambient).toBe('off');
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    fireEvent(document, new Event('visibilitychange'));
    expect(document.documentElement.dataset.pageVisibility).toBe('hidden');
  });
});
