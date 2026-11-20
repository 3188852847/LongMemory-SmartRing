import {test,expect,type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {syntheticResponse} from '../src/features/data-workspace/syntheticFixtures';

const dist=resolve(import.meta.dirname,'../dist');
const pages=[
  {path:'/device',task:'常用控制',normal:'应用音量',empty:'不可控',failure:'不可控'},
];

async function syntheticPage(page:Page,mode:'normal'|'empty'|'failure') {
  const writes:string[]=[];
  await page.route('**/*',async route=>{
    const request=route.request();const url=new URL(request.url());
    if(url.hostname!=='127.0.0.1')return route.abort();
    if(url.pathname.startsWith('/api/')) {
      if(request.method()!=='GET'){writes.push(url.pathname);return route.fulfill({status:405,json:{error:'synthetic_read_only'}});}
      // 引擎身份属于页面装配前提；本矩阵验证的是已知旧引擎下各业务读取失败。
      if(mode==='failure' && !['/api/session','/api/memory-engine/identity'].includes(url.pathname))return route.fulfill({status:503,json:{error:'http_503'}});
      return route.fulfill({json:syntheticResponse(url.pathname+url.search,mode==='normal')});
    }
    if(request.isNavigationRequest())return route.fulfill({contentType:'text/html',body:await readFile(resolve(dist,'index.html'))});
    if(url.pathname.startsWith('/react-chat/')) {
      const path=resolve(dist,decodeURIComponent(url.pathname.slice('/react-chat/'.length)));
      if(!path.startsWith(dist+sep))return route.abort();
      const mime:Record<string,string>={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};
      return route.fulfill({contentType:mime[extname(path)]??'application/octet-stream',body:await readFile(path)});
    }
    return route.abort();
  });
  return writes;
}

for(const viewport of [{width:1366,height:768},{width:1440,height:900},{width:480,height:800}]) {
  for(const target of pages)for(const mode of ['normal','empty','failure'] as const) {
    test(`${viewport.width}×${viewport.height} ${target.path} ${mode}`,async({page})=>{
      await page.setViewportSize(viewport);const writes=await syntheticPage(page,mode);
      await page.goto(target.path);
      const task=page.getByRole('button',{name:target.task,exact:true});
      await expect(task).toBeVisible();
      const box=await task.boundingBox();expect(box!.y+box!.height).toBeLessThanOrEqual(viewport.height);
      if(target.path==='/device') {
        if(mode==='normal')await expect(page.getByRole('button',{name:'应用音量'})).toBeEnabled();
        else await expect(page.getByRole('button',{name:'应用音量'})).toBeDisabled();
      }
      else await expect(page.getByText(mode==='normal'?target.normal:mode==='empty'?target.empty:target.failure,{exact:false}).first()).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
      expect(writes).toEqual([]);
    });
  }
}
