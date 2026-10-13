import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {describe, expect, test, vi} from 'vitest';
import {ManualMemoryAdd} from './ManualMemoryAdd';

describe('ManualMemoryAdd', () => {
  test('通过统一明确记忆接口保存并回报实际结果', async () => {
    const request = vi.fn().mockResolvedValue({
      kind: 'include', status: 'applied', notice: '已保存为 L1 长期事实',
      target_memory_ids: ['l1-test'], l0_message_id: 'l0-test',
    });
    const onSaved = vi.fn();
    render(<ManualMemoryAdd api={{request} as never} disabled={false} onSaved={onSaved}/>);

    fireEvent.click(screen.getByRole('button', {name: '明确添加'}));
    fireEvent.change(screen.getByLabelText('要明确记住的事实'), {target: {value: '我的猫叫豆包。'}});
    fireEvent.click(screen.getByRole('button', {name: '保存为长期事实'}));

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/api/memory-commands/include', 'POST', {content: '我的猫叫豆包。'},
    ));
    expect(await screen.findByText('已保存为 L1 长期事实')).not.toBeNull();
    expect(onSaved).toHaveBeenCalledWith('l1-test');
  });
});
