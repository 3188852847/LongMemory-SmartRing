import {useState} from 'react';
import {describe, expect, test} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {MemoryRouter, useLocation, useNavigate} from 'react-router-dom';
import {DataWorkspace, useWorkspaceParam} from './DataWorkspace';

function Fixture() {
  const [view,setView] = useWorkspaceParam('view','list',['list','review']);
  const [filter,setFilter] = useWorkspaceParam('state','all',['all','active']);
  const [draft,setDraft] = useState('');
  const location=useLocation();
  const navigate=useNavigate();
  return <><output aria-label="URL">{location.search}</output>
    <button onClick={()=>{setFilter('active',false);setView('review');}}>同时切换</button>
    <button onClick={()=>navigate(-1)}>返回</button>
    <DataWorkspace label="合成数据" activeKey={view} onChange={setView} items={[
      {key:'list',label:'列表',children:<input aria-label="筛选" value={filter} readOnly/>},
      {key:'review',label:'复核',children:<input aria-label="草稿" value={draft} onChange={e=>setDraft(e.target.value)}/>},
    ]}/></>;
}

describe('数据工作区浏览坐标',()=>{
  test('多项 URL 更新互不覆盖，浏览器返回恢复原视图',()=>{
    render(<MemoryRouter initialEntries={['/synthetic?keep=1']}><Fixture/></MemoryRouter>);
    fireEvent.click(screen.getByRole('button',{name:'同时切换'}));
    const url=screen.getByLabelText('URL').textContent!;
    expect(new URLSearchParams(url).get('keep')).toBe('1');
    expect(new URLSearchParams(url).get('state')).toBe('active');
    expect(screen.getByRole('button',{name:'复核'}).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button',{name:'返回'}));
    expect(screen.getByRole('button',{name:'列表'}).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByLabelText('筛选').getAttribute('value')).toBe('all');
  });
  test('任务切换保留草稿和各自滚动位置，隐藏任务不占阅读焦点',()=>{
    render(<MemoryRouter initialEntries={['/scroll?view=review']}><Fixture/></MemoryRouter>);
    fireEvent.change(screen.getByRole('textbox',{name:'草稿'}),{target:{value:'尚未保存的合成复核'}});
    const panel=screen.getByRole('region',{name:'复核'});
    panel.scrollTop=180;fireEvent.scroll(panel);
    fireEvent.click(screen.getByRole('button',{name:'列表'}));
    expect(screen.queryByRole('textbox',{name:'草稿'})).toBeNull();
    fireEvent.click(screen.getByRole('button',{name:'复核'}));
    expect(screen.getByRole('textbox',{name:'草稿'}).getAttribute('value')).toBe('尚未保存的合成复核');
    expect(screen.getByRole('region',{name:'复核'}).scrollTop).toBe(180);
  });
  test('未知分类回到默认任务，保留无关深链接参数',()=>{
    render(<MemoryRouter initialEntries={['/invalid?view=unknown&memory_id=synthetic']}><Fixture/></MemoryRouter>);
    expect(screen.getByRole('button',{name:'列表'}).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button',{name:'复核'}));
    expect(screen.getByLabelText('URL').textContent).toContain('memory_id=synthetic');
  });
});
