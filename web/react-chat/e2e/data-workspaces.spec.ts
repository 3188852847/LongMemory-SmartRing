import {test,expect,type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
import {syntheticResponse} from '../src/features/data-workspace/syntheticFixtures';

const dist=resolve(import.meta.dirname,'../dist');
const pages=[
  {path:'/memories',task:'浏览记忆',normal:'合成事实：用户喜欢茶。',empty:'没有符合条件的 L1',failure:'无法读取记忆服务'},
  {path:'/memory-quality',task:'问题队列',normal:'合成问题样本',empty:'目前没有待核对问题',failure:'无法读取质量样本'},
  {path:'/scenarios',task:'场景与候选',normal:'合成场景',empty:'尚无 L2 生活场景',failure:'无法读取记忆服务'},
  {path:'/personas',task:'统一画像',normal:'合成画像',empty:'尚无已接受的画像认识',failure:'无法读取记忆服务'},
  {path:'/device',task:'常用控制',normal:'应用音量',empty:'不可控',failure:'不可控'},
  {path:'/experiments-react',task:'档案与逐题对照',normal:'合成模型',empty:'没有匹配的实验',failure:'实验档案读取失败'},
];

async function syntheticPage(page:Page,mode:'normal'|'empty'|'failure') {
  const writes:string[]=[];
  await page.route('**/*',async route=>{
    const request=route.request();const url=new URL(request.url());
    if(url.hostname!=='127.0.0.1')return route.abort();
    if(url.pathname.startsWith('/api/')) {
      if(request.method()!=='GET'){writes.push(url.pathname);return route.fulfill({status:405,json:{error:'synthetic_read_only'}});}
      // 引擎身份属于页面装配前提；本矩阵验证的是已知旧引擎下各业务读取失败。
      if(mode==='failure' && !['/api/session','/api/memory-engine/identity','/api/memory-config'].includes(url.pathname))return route.fulfill({status:503,json:{error:'http_503'}});
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

test('场景搜索、抽屉、刷新与浏览器返回保留浏览坐标',async({page})=>{
  const writes=await syntheticPage(page,'normal');await page.goto('/scenarios?q=合成&state=active');
  const search=page.getByRole('textbox',{name:'搜索已加载场景'});await expect(search).toHaveValue('合成');
  await page.getByRole('button',{name:'查看来源',exact:true}).click();
  await expect(page).toHaveURL(/scenario_id=synthetic-scenario/);
  await expect(page.getByText('L2 场景详情', {exact:true})).toBeVisible();
  await page.locator('.ant-drawer-close').click();await expect(search).toHaveValue('合成');
  await page.getByRole('button',{name:'整理状态',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'搜索已加载场景'})).toBeHidden();
  await page.reload();await expect(page.getByRole('button',{name:'整理状态',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:'场景与候选',exact:true}).click();await expect(search).toHaveValue('合成');
  await page.goBack();await expect(page.getByRole('button',{name:'整理状态',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.goForward();await expect(search).toHaveValue('合成');
  expect(writes).toEqual([]);
});

test('放大字号、减少动画与键盘切换仍可找到任务，实验同题并排',async({page})=>{
  await syntheticPage(page,'normal');await page.setViewportSize({width:1440,height:900});
  await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/experiments-react');
  await page.evaluate(()=>document.documentElement.style.fontSize='20px');
  await expect(page.getByText('合成回答 no_memory')).toBeVisible();
  await expect(page.getByText('合成回答 longmemory_v1')).toBeVisible();
  const columns=page.locator('.question-grid-react > .ant-card');expect(await columns.count()).toBe(2);
  const left=await columns.nth(0).boundingBox(),right=await columns.nth(1).boundingBox();
  // 1440px 主从布局应给逐题比较足够宽度；坐标证明两组实际并排。
  expect(right!.x).toBeGreaterThan(left!.x);expect(Math.abs(right!.y-left!.y)).toBeLessThan(2);
  const first=page.getByRole('button',{name:'档案与逐题对照',exact:true});await first.focus();await page.keyboard.press('Tab');
  await expect(page.getByRole('button',{name:'准备档案',exact:true})).toBeFocused();await page.keyboard.press('Tab');
  await expect(page.getByRole('button',{name:'运行实验',exact:true})).toBeFocused();await page.keyboard.press('Enter');
  await expect(page.getByRole('button',{name:'运行实验',exact:true})).toHaveAttribute('aria-pressed','true');
});
