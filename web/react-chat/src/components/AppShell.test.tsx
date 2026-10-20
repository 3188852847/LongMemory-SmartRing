import {KnownMemoryEngine} from '../tests/memoryEngine';
import {describe, expect, test} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {AppShell, ConsoleNav} from './AppShell';

describe('控制台共享导航', () => {
  test('React 页面使用内部路由，旧页面仍保留回退入口', () => {
    render(<MemoryRouter><KnownMemoryEngine kind="legacy"><AppShell subtitle="测试" sidebar={<ConsoleNav active="chat" legacyPath="/chat"/>}>
      <h1>页面内容</h1>
    </AppShell></KnownMemoryEngine></MemoryRouter>);

    expect(screen.getByRole('link', {name: '智慧圆屏'}).getAttribute('href')).toBe('/overview');
    expect(screen.getByRole('link', {name: '系统总览'}).getAttribute('href')).toBe('/overview');
    expect(screen.getByRole('link', {name: '原话与事实'}).getAttribute('href')).toBe('/memories');
    expect(screen.getByRole('link', {name: '设备状态'}).getAttribute('href')).toBe('/device');
    expect(screen.getByRole('link', {name: '圆屏预览'}).getAttribute('href')).toBe('/display-preview');
    expect(screen.getByRole('link', {name: '用户画像'}).getAttribute('href')).toBe('/personas');
    expect(screen.getByRole('link', {name: '设置中心'}).getAttribute('href')).toBe('/settings');
    expect(screen.getByRole('link', {name: '打开原版页面'}).getAttribute('href')).toBe('/chat');
    expect(screen.getByRole('link', {name: '跳到主要内容'}).getAttribute('href')).toBe('#main-content');
    expect(screen.getByText('本机个人空间')).toBeTruthy();
    expect(screen.getByText('日常使用')).toBeTruthy();
    expect(screen.getByText('长期记忆')).toBeTruthy();
    expect(screen.getByText('控制与观察')).toBeTruthy();
    expect(screen.getByRole('heading', {name: '页面内容'})).toBeTruthy();
    expect(screen.getByRole('link', {name:'文字聊天'}).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('main').getAttribute('tabindex')).toBe('-1');
    const toggle = screen.getByRole('button', {name:'展开导航'});
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(screen.getByRole('navigation', {name:'控制台导航'}), {key:'Escape'});
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(toggle);
  });
});
