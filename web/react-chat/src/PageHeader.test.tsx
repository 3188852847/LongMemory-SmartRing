import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {PageHeader} from './PageHeader';

describe('PageHeader', () => {
  it('按任务、说明、状态和操作的顺序呈现页面入口', () => {
    render(<PageHeader eyebrow="长期记忆" title="原始与原子记忆" description="核对来源关系" meta="测试数据库" action={<button>刷新</button>}/>);
    expect(screen.getByText('长期记忆')).toBeTruthy();
    expect(screen.getByRole('heading', {name:'原始与原子记忆'})).toBeTruthy();
    expect(screen.getByText('核对来源关系')).toBeTruthy();
    expect(screen.getByText('测试数据库')).toBeTruthy();
    expect(screen.getByRole('button', {name:'刷新'})).toBeTruthy();
  });
});
