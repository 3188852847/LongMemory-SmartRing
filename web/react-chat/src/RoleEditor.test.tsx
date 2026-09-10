import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {describe, expect, test, vi} from 'vitest';
import {ChatApi} from './api';
import {RoleEditor} from './RoleEditor';

describe('助手角色设置', () => {
  test('恢复推荐表达只修改草稿并保留角色正文', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      current:{revision:4,name:'自定义角色',prompt:'原始角色正文',saved_at:null},
      presets:[],web:'next_turn',device:'not_synced',
    });
    render(<RoleEditor api={new ChatApi()} disabled={false} onSaved={() => undefined}/>);
    fireEvent.click(screen.getByRole('button', {name:/助手角色设置/}));
    await waitFor(() => expect(screen.getByDisplayValue('自定义角色')).toBeTruthy());
    fireEvent.click(screen.getByRole('switch', {name:'启用结构化表达偏好'}));
    fireEvent.change(screen.getByLabelText('希望助手怎么称呼你（可留空）'), {target:{value:'小林'}});
    fireEvent.click(screen.getByRole('button', {name:/恢复推荐表达草稿/}));

    expect((screen.getByLabelText('希望助手怎么称呼你（可留空）') as HTMLInputElement).value).toBe('');
    expect(screen.getByDisplayValue('自定义角色')).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(1);
  });
});
