import {fireEvent, render, screen} from '@testing-library/react';
import {describe, expect, test} from 'vitest';
import {MemoryCommandHelp} from './MemoryCommandHelp';

describe('MemoryCommandHelp', () => {
  test('只在用户打开后展示固定命令与删除边界', () => {
    render(<MemoryCommandHelp/>);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', {name: '记忆命令'}));
    expect(screen.getByRole('dialog', {name: '可直接使用的记忆命令'})).not.toBeNull();
    expect(screen.getByText('请记住：我叫小林')).not.toBeNull();
    expect(screen.getByText('确认删除这条记忆')).not.toBeNull();
    expect(screen.getByText(/删除 L1 不等于删除 L0/)).not.toBeNull();
  });
});
