import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ChatApi} from '../api';
import {hyIdentity} from '../tests/memoryEngine';
import {afterEach, expect, test, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {createMemoryRouter, Link, RouterProvider, useSearchParams} from 'react-router-dom';
import {RouteWorkspace} from './RouteWorkspace';

afterEach(() => vi.restoreAllMocks());
function Page() {
  const [, update] = useSearchParams();
  return <main id="main-content" tabIndex={-1}><input aria-label="编辑" onChange={()=>update({tab:'draft'})}/><Link to="/other">新页面</Link></main>;
}
test('页内分类保留输入焦点，新页面导航将焦点交给主内容', async () => {
  vi.spyOn(ChatApi.prototype,'bootstrap').mockResolvedValue(undefined);
  vi.spyOn(ChatApi.prototype,'request').mockResolvedValue(hyIdentity);
  vi.spyOn(window,'scrollTo').mockImplementation(()=>undefined);
  const router=createMemoryRouter([{element:<RouteWorkspace/>,children:[
    {path:'/start',element:<Page/>},{path:'/other',element:<main id="main-content" tabIndex={-1}>目标页面</main>},
  ]}],{initialEntries:['/start']});
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><RouterProvider router={router}/></QueryClientProvider>);
  const input=screen.getByRole('textbox',{name:'编辑'});input.focus();
  fireEvent.change(input,{target:{value:'合成草稿'}});
  expect(document.activeElement).toBe(input);
  fireEvent.click(screen.getByRole('link',{name:'新页面'}));
  await screen.findByText('目标页面');
  expect(document.activeElement).toBe(screen.getByRole('main'));
});
