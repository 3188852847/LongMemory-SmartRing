import {useState} from 'react';
import {afterEach, expect, test, vi} from 'vitest';
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {createMemoryRouter, Link, Outlet, RouterProvider, useSearchParams} from 'react-router-dom';
import {UnsavedChangesProvider, useUnsavedChanges} from './UnsavedChanges';

function Draft() {
  const [text, setText] = useState('');
  const [, setParams] = useSearchParams();
  useUnsavedChanges(Boolean(text), '有未保存的合成草稿。');
  return <><input aria-label="草稿" value={text} onChange={event => setText(event.target.value)}/>
    <button onClick={() => setParams({tab: 'other'})}>切分类</button><Link to="/other">离页</Link></>;
}
function mount() {
  const router = createMemoryRouter([{element: <UnsavedChangesProvider><Outlet/></UnsavedChangesProvider>,
    children: [{path: '/draft', element: <Draft/>}, {path: '/other', element: <p>另一页</p>}]}],
    {initialEntries: ['/other', '/draft'], initialIndex: 1});
  render(<RouterProvider router={router}/>);
  fireEvent.change(screen.getByRole('textbox', {name: '草稿'}), {target: {value: '合成未保存内容'}});
  return router;
}
afterEach(() => vi.restoreAllMocks());

test('分类切换保留草稿；拒绝跨页导航不卸载；允许后完成导航', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  mount();
  fireEvent.click(screen.getByRole('button', {name: '切分类'}));
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('link', {name: '离页'}));
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  expect(screen.getByRole('textbox', {name: '草稿'}).getAttribute('value')).toBe('合成未保存内容');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('link', {name: '离页'}));
  expect(await screen.findByText('另一页')).toBeTruthy();
});

test('拒绝浏览器后退保持路由与草稿；刷新事件被保护；清除草稿后不阻挡', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const router = mount();
  await act(async () => {await router.navigate(-1);});
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  expect(router.state.location.pathname).toBe('/draft');
  const unload = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  fireEvent.change(screen.getByRole('textbox', {name: '草稿'}), {target: {value: ''}});
  await act(async () => {await router.navigate(-1);});
  expect(await screen.findByText('另一页')).toBeTruthy();
  expect(confirm).toHaveBeenCalledTimes(1);
});

test('记忆内分类切换保留草稿，转到机制页前保护即将卸载的编辑', async () => {
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  const router=createMemoryRouter([{element:<UnsavedChangesProvider><Outlet/></UnsavedChangesProvider>,children:[
    {path:'/memories',element:<Draft/>},
  ]}],{initialEntries:['/memories?view=items']});
  render(<RouterProvider router={router}/>);
  fireEvent.change(screen.getByRole('textbox',{name:'草稿'}),{target:{value:'合成编辑'}});
  await act(async()=>{await router.navigate('/memories?view=profile');});
  expect(confirm).not.toHaveBeenCalled();
  await act(async()=>{await router.navigate('/memories?view=mechanisms');});
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(router.state.location.search).toBe('?view=profile');
  expect((screen.getByRole('textbox',{name:'草稿'}) as HTMLInputElement).value).toBe('合成编辑');
  confirm.mockReturnValue(true);
  await act(async()=>{await router.navigate('/memories?view=mechanisms');});
  expect(router.state.location.search).toBe('?view=mechanisms');
});
