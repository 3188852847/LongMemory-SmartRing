import {expect, test, type Page} from '@playwright/test';
import {syntheticResponse} from '../src/features/data-workspace/syntheticFixtures';

async function appearance(page:Page, motion:'full'|'reduce', size='normal') {
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.addInitScript(({motion,size})=>localStorage.setItem('longmemory:chat-appearance:v3',
    JSON.stringify({theme:'future',motion,size,density:'comfortable',chatWidth:'focused'})),{motion,size});
}
async function gone(page:Page) {
  await expect(page.locator('.ant-modal-wrap:visible')).toHaveCount(0);
  await expect(page.locator('.ant-modal-mask:visible')).toHaveCount(0);
  await expect(page.getByRole('dialog')).toHaveCount(0);
}

for(const width of [1440,390]) for(const motion of ['full','reduce'] as const) {
  test(`R1 ${width} ${motion} 角色与删除确认的键盘关闭真实释放遮罩`,async({page},info)=>{
    await page.setViewportSize({width,height:width===390?844:900});await appearance(page,motion);
    await page.goto('/settings?tab=role');
    const trigger=page.getByRole('button',{name:'助手角色设置',exact:true});
    for(const close of ['escape','enter','pointer'] as const) {
      await trigger.click();
      const modal=page.getByRole('dialog',{name:'助手角色设置'});
      await expect(modal.getByLabel('角色名称')).toBeEnabled();
      if(close==='escape') await page.keyboard.press('Escape');
      else if(close==='enter') {await modal.getByRole('button',{name:'Close',exact:true}).focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');await page.keyboard.press('Enter');}
      else {await page.keyboard.press('Tab');await modal.getByRole('button',{name:'Close',exact:true}).click();}
      await info.attach(`modal-${close}`,{body:JSON.stringify(await page.locator('.ant-modal').evaluateAll(nodes=>nodes.map(node=>({classes:node.className,
        animation:getComputedStyle(node).animationName,transition:getComputedStyle(node).transitionProperty})))),contentType:'application/json'});
      await gone(page);await expect(trigger).toBeFocused();
    }
    await page.getByRole('tab',{name:'外观与阅读',exact:true}).click();
    await expect(page.getByRole('combobox',{name:'主题'})).toBeVisible();
  });
}

test('R1 full 脏角色 Esc 拒绝放弃继续保护，明确放弃才关闭',async({page})=>{
  await appearance(page,'full');await page.goto('/settings?tab=role');
  const trigger=page.getByRole('button',{name:'助手角色设置',exact:true});await trigger.click();
  const modal=page.getByRole('dialog',{name:'助手角色设置'});
  const name=modal.getByLabel('角色名称');await expect(name).toBeEnabled();await name.fill('合成未保存角色');
  await Promise.all([page.waitForEvent('dialog').then(dialog=>dialog.dismiss()),page.keyboard.press('Escape')]);
  await expect(modal).toBeVisible();await expect(name).toHaveValue('合成未保存角色');
  await Promise.all([page.waitForEvent('dialog').then(dialog=>dialog.accept()),page.keyboard.press('Escape')]);
  await gone(page);await expect(trigger).toBeFocused();
});

test('R3 自定义保存不沿用另一个对象的预览选择成功提示',async({page})=>{
  const load=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/round-skins');
  await page.goto('/display-preview?tab=skin');
  const initial=await (await load).json();
  const other=initial.skins.find((skin:{id:string})=>skin.id!==initial.selected_skin && skin.id!==initial.custom_skin_id);
  await page.getByRole('combobox',{name:'圆屏皮肤'}).click();
  await page.locator('.ant-select-dropdown:visible').getByText(other.name,{exact:true}).click();
  await page.getByRole('button',{name:'保存预览选择',exact:true}).click();
  await expect(page.getByText('电脑预览选择已保存；真机尚未下发。',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'从当前皮肤开始编辑',exact:true}).click();
  await page.getByLabel('皮肤颜色：背景',{exact:true}).fill('#112233');
  await page.getByRole('button',{name:'保存为“我的自定义皮肤”',exact:true}).click();
  await expect(page.getByRole('region',{name:'本机自定义皮肤编辑器'})).toHaveCount(0);
  await expect(page.getByText('电脑预览选择已保存；真机尚未下发。',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'保存预览选择',exact:true})).toBeEnabled();
});

for(const width of [390,1366]) test(`R4 ${width} 更大字号九种交互阶段完整可读`,async({page},info)=>{
  await page.setViewportSize({width,height:width===390?844:768});await appearance(page,'reduce','larger');
  await page.goto('/display-preview');
  for(const name of ['启动','待机','已唤醒','聆听','思考','说话','被打断','没听清','错误']) {
    const input=page.getByRole('radio',{name,exact:true});
    const label=input.locator('xpath=ancestor::label');await label.scrollIntoViewIfNeeded();
    await expect(label).toBeVisible();
    // 组件可把原生 input 隐藏在可见标签下；真正要保证的是文字完整、目标可点击。
    const text=label.getByText(name,{exact:true});
    expect(await text.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
    expect(await text.evaluate(node=>getComputedStyle(node).textOverflow)).not.toBe('ellipsis');
    expect(await label.evaluate(node=>node.scrollWidth<=node.clientWidth+1)).toBe(true);
    expect(await label.evaluate(node=>getComputedStyle(node).textOverflow)).not.toBe('ellipsis');
    const box=await label.boundingBox();expect(box!.x+box!.width).toBeLessThanOrEqual(width+1);
    expect(box!.height).toBeGreaterThanOrEqual(44);
    await label.click();await expect(input).toBeChecked();
    await input.focus();await expect(input).toBeFocused();await page.keyboard.press('Space');await expect(input).toBeChecked();
  }
  await info.attach('完整交互阶段标签',{body:await page.screenshot({fullPage:true}),contentType:'image/png'});
  await page.screenshot({path:info.outputPath(`r4-labels-${width}.png`),fullPage:true});
});
