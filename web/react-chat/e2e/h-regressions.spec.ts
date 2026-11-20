import {expect, test, type Page} from '@playwright/test';
import {syntheticResponse} from '../src/features/data-workspace/syntheticFixtures';

async function appearance(page:Page, motion:'full'|'reduce', size='normal') {
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.addInitScript(({motion,size})=>localStorage.setItem('longmemory:chat-appearance:v3',
    JSON.stringify({theme:'future',motion,size,density:'comfortable',chatWidth:'focused'})),{motion,size});
}
for (const width of [1440, 390]) {
  test(`角色设置在 ${width}px 直接可编辑，跨页签保留草稿`, async ({page}) => {
    await page.setViewportSize({width, height:900});
    await page.goto('/settings?tab=role');
    const prompt = page.getByLabel('人格卡', {exact:true});
    await expect(prompt).toBeEnabled();
    await prompt.fill('合成人格草稿');
    await page.getByRole('tab', {name:'外观与阅读'}).click();
    await page.getByRole('tab', {name:'角色设置'}).click();
    await expect(prompt).toHaveValue('合成人格草稿');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

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
