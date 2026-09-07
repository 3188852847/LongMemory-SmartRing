import {describe, expect, test} from 'vitest';
import {render, screen} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {RoundDisplayApp, resolveRoundDisplay} from './RoundDisplayApp';

describe('圆屏状态协议与模拟器', () => {
  test('阻塞性系统状态覆盖普通交互状态', () => {
    expect(resolveRoundDisplay('speaking', 'network_offline')).toMatchObject({title: '网络未连接', focus: 'notice'});
    expect(resolveRoundDisplay('thinking', 'updating')).toMatchObject({title: '正在更新', focus: 'progress'});
  });

  test('充电与低电量不覆盖当前交互焦点', () => {
    expect(resolveRoundDisplay('listening', 'charging').title).toBe('聆听中');
    expect(resolveRoundDisplay('speaking', 'low_battery').title).toBe('回应中');
  });

  test('默认页面明确模拟边界并提供三层控制', () => {
    render(<MemoryRouter><RoundDisplayApp/></MemoryRouter>);
    expect(screen.getByRole('heading', {name: '圆屏状态预览'})).toBeTruthy();
    expect(screen.getByText(/画布：360 × 360 px/)).toBeTruthy();
    expect(screen.getByText('这是设计模拟器，不是真实设备控制器')).toBeTruthy();
    expect(screen.getByRole('region', {name: '圆屏模拟画布'})).toBeTruthy();
    expect(screen.getByText('1. 交互阶段')).toBeTruthy();
    expect(screen.getByText('2. 情绪表达')).toBeTruthy();
    expect(screen.getByText('3. 系统覆盖')).toBeTruthy();
  });
});
