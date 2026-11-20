import {render, screen} from '@testing-library/react';
import {expect, test, vi} from 'vitest';
import type {ChatApi} from '../../api';
import {MemoryBackendSettings} from './MemoryBackendSettings';

test('只读取运行状态，不提供切换入口', async () => {
  const request = vi.fn().mockResolvedValue({enabled:true, current_backend:'hy_memory'});
  render(<MemoryBackendSettings api={{request} as unknown as ChatApi} disabled={false}/>);
  expect(await screen.findByText(/当前服务正在使用 Hy-Memory/)).toBeTruthy();
  expect(screen.queryByRole('combobox')).toBeNull();
  expect(screen.queryByRole('button')).toBeNull();
  expect(request.mock.calls).toEqual([['/api/memory-backends']]);
});
