import {test, expect} from '@playwright/test';
import {spawn, type ChildProcess} from 'node:child_process';
import {resolve} from 'node:path';
import {mkdir, writeFile} from 'node:fs/promises';

let host: ChildProcess;
let origin: string;
const token = 'synthetic-launcher-browser-test-token';

test.beforeAll(async () => {
  const root = resolve(process.cwd(), '../..');
  host = spawn(resolve(root, '.venv/Scripts/python.exe'),
    [resolve(root, 'scripts/development/playwright_launcher.py')], {cwd: root, windowsHide: true});
  origin = await new Promise<string>((success, failure) => {
    const timer = setTimeout(() => failure(new Error('合成启动器未在期限内启动')), 10_000);
    let output = '';
    host.once('error', failure);
    host.once('exit', code => failure(new Error(`合成启动器提前退出 ${code}`)));
    host.stdout!.on('data', data => {
      output += data.toString();
      if (output.includes('\n')) {
        clearTimeout(timer);
        success(JSON.parse(output.split('\n')[0]).origin);
      }
    });
  });
});
test.afterAll(() => host?.kill());

test('真实本机主机与 React 页面启动、停止闭环', async ({page}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${origin}/#token=${token}`);
  await expect(page.getByRole('button', {name: '开启陪伴'})).toBeEnabled();
  expect(new URL(page.url()).hash).toBe('');
  if (process.env.LAUNCHER_SCREENSHOT_DIR) {
    await mkdir(process.env.LAUNCHER_SCREENSHOT_DIR, {recursive: true});
    for (const width of [1440, 1040]) {
      await page.setViewportSize({width, height: 800});
      await page.screenshot({path: resolve(process.env.LAUNCHER_SCREENSHOT_DIR, `launcher-${width}.png`), fullPage: true});
    }
  }
  await page.getByRole('button', {name: '开启陪伴'}).click();
  await expect(page.getByRole('button', {name: /进入陪伴空间/})).toBeEnabled();
  await page.getByRole('button', {name: '停止服务', exact: true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', {name: '继续运行'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.getByRole('button', {name: /进入陪伴空间/})).toBeEnabled();
  await page.getByRole('button', {name: '停止服务', exact: true}).click();
  await page.getByRole('dialog').getByRole('button', {name: '停止服务', exact: true}).click();
  await expect(page.getByRole('button', {name: '开启陪伴'})).toBeEnabled();
  expect(errors).toEqual([]);
});

test('窄屏设置和减少动画正常，缺少权限不开放启动', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.goto(`${origin}/#token=${token}`);
  await expect(page.getByRole('button', {name: /启动设置/})).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator('.orb-orbit').first().evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  await page.getByRole('button', {name: /启动设置/}).click();
  await expect(page.getByLabel('电脑局域网 IP')).toBeVisible();
  for (const input of await page.locator('.launcher-drawer .ant-select-input').all()) {
    expect(await input.evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  }
  await expect.poll(async () => {
    const bounds = await page.locator('.ant-drawer-content-wrapper').boundingBox();
    return bounds ? Math.round(bounds.x) : -1;
  }).toBe(0);
  if (process.env.LAUNCHER_SCREENSHOT_DIR) {
    await page.screenshot({path: resolve(process.env.LAUNCHER_SCREENSHOT_DIR, 'launcher-settings-390.png'), fullPage: true});
    const controls = await page.locator('.launcher-drawer .ant-select').evaluateAll(elements => elements.map(element => ({
      html: element.outerHTML.slice(0, 1000),
      parts: Array.from(element.querySelectorAll('input,span')).slice(0, 12).map(part => {
        const style = getComputedStyle(part);
        return {class: part.className, color: style.color, background: style.backgroundColor, opacity: style.opacity};
      }),
    })));
    await writeFile(resolve(process.env.LAUNCHER_SCREENSHOT_DIR, 'drawer-style-inspection.json'), JSON.stringify(controls, null, 2));
  }
  await page.getByLabel('电脑局域网 IP').fill('192.168.1.22');
  await page.getByRole('button', {name: '保存设置'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.goto(origin);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', {name: '开启陪伴'})).toBeDisabled();
});
