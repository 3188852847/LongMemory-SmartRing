import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {describe, expect, test, vi} from 'vitest';
import {ChatApi} from '../../api';
import {RoleEditor} from './RoleEditor';

describe('助手角色设置', () => {
  test('恢复推荐表达只修改草稿并保留角色正文', async () => {
    const request = vi.spyOn(ChatApi.prototype, 'request').mockResolvedValue({
      current:{revision:4,name:'自定义角色',prompt:'原始角色正文',saved_at:null},
      history:[
        {revision:4,name:'自定义角色',prompt:'原始角色正文',saved_at:null},
        {revision:3,name:'旧角色',prompt:'旧角色正文',saved_at:'2026-09-09T12:00:00Z'},
      ],
      presets:[],web:'next_turn',device:'not_synced',
    });
    render(<RoleEditor api={new ChatApi()} disabled={false} onSaved={() => undefined}/>);
    fireEvent.click(screen.getByRole('button', {name:/助手角色设置/}));
    await waitFor(() => expect(screen.getByDisplayValue('自定义角色')).toBeTruthy());
    expect(screen.getByRole('combobox', {name:'载入角色历史版本'})).toBeTruthy();
    fireEvent.click(screen.getByRole('switch', {name:'启用结构化表达偏好'}));
    fireEvent.change(screen.getByLabelText('希望助手怎么称呼你（可留空）'), {target:{value:'小林'}});
    fireEvent.click(screen.getByRole('button', {name:/恢复推荐表达草稿/}));

    expect((screen.getByLabelText('希望助手怎么称呼你（可留空）') as HTMLInputElement).value).toBe('');
    expect(screen.getByDisplayValue('自定义角色')).toBeTruthy();
    fireEvent.mouseDown(screen.getByLabelText('载入角色历史版本'));
    fireEvent.click(await screen.findByText('修订 3 · 旧角色'));
    expect(screen.getByDisplayValue('旧角色')).toBeTruthy();
    expect(screen.getByText(/已将修订 3 载入草稿；点击保存后才会创建新版本/)).toBeTruthy();
    expect(request).toHaveBeenCalledTimes(1);
  });
});
