import {describe, expect, test} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {AppShell, ConsoleNav} from './AppShell';

describe('控制台共享导航', () => {
  test('React 页面使用内部路由，旧页面仍保留回退入口', () => {
    render(<MemoryRouter><AppShell subtitle="测试" sidebar={<ConsoleNav active="chat" legacyPath="/chat"/>}>
      <h1>页面内容</h1>
    </AppShell></MemoryRouter>);

    expect(screen.getByRole('link', {name: 'LongMemory'}).getAttribute('href')).toBe('/chat-react');
    expect(screen.getByRole('link', {name: '原始与原子记忆'}).getAttribute('href')).toBe('/memories');
    expect(screen.getByRole('link', {name: '设备状态'}).getAttribute('href')).toBe('/device');
    expect(screen.getByRole('link', {name: '用户画像'}).getAttribute('href')).toBe('/personas');
    expect(screen.getByRole('link', {name: '设置中心'}).getAttribute('href')).toBe('/settings');
    expect(screen.getByRole('link', {name: '打开原版页面'}).getAttribute('href')).toBe('/chat');
    expect(screen.getByText('日常使用')).toBeTruthy();
    expect(screen.getByText('长期记忆')).toBeTruthy();
    expect(screen.getByText('控制与观察')).toBeTruthy();
    expect(screen.getByRole('heading', {name: '页面内容'})).toBeTruthy();
  });
});
