import {describe, expect, test} from 'vitest';
import {createConsoleQueryClient} from './queryClient';

describe('控制台请求策略', () => {
  test('默认不重试读写请求，避免隐式重放用户操作', () => {
    const client = createConsoleQueryClient();
    expect(client.getDefaultOptions().queries?.retry).toBe(false);
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
    client.clear();
  });
});
