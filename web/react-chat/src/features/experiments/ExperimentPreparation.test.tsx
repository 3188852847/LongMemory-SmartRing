import {describe,expect,test,vi} from 'vitest';
import {fireEvent,render,screen} from '@testing-library/react';
import {ExperimentPreparation,offlinePreparation,retrievalPreparation} from './ExperimentPreparation';

describe('实验准备入口',()=>{
  test('给出真实离线入口并能回到档案与运行，不执行命令',()=>{
    const archive=vi.fn(), run=vi.fn();
    render(<ExperimentPreparation onArchive={archive} onRun={run}/>);
    expect(screen.getByText(offlinePreparation)).toBeTruthy();
    expect(screen.getByText((_,node)=>node?.tagName==='CODE' && node.textContent===retrievalPreparation)).toBeTruthy();
    expect(retrievalPreparation).toContain('请替换为上一步输出的实际编号');
    fireEvent.click(screen.getByRole('button',{name:'回到档案并刷新'}));
    fireEvent.click(screen.getByRole('button',{name:'前往运行实验核对能力'}));
    expect(archive).toHaveBeenCalledOnce();expect(run).toHaveBeenCalledOnce();
  });
});
