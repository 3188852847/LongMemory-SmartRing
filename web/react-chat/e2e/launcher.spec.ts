import {test, expect} from '@playwright/test';
import {spawn, type ChildProcess} from 'node:child_process';
import {resolve} from 'node:path';
import {mkdir, writeFile} from 'node:fs/promises';

let host: ChildProcess;
let origin: string;
const token = 'synthetic-launcher-browser-test-token';

test.beforeAll(async () => {
  const root = resolve(process.cwd(), '../..');
  await mkdir(resolve(root, 'data/test-tmp/browser-j'), {recursive: true});
  host = spawn(process.env.SMART_RING_TEST_PYTHON || resolve(root, '.venv/Scripts/python.exe'),
    [resolve(root, 'scripts/development/playwright_launcher.py')], {cwd: root, windowsHide: true,
      env: {...process.env, PYTHONPATH: resolve(root, 'src'), PYTHONDONTWRITEBYTECODE:'1',
        TEMP: resolve(root, 'data/test-tmp/browser-j'), TMP: resolve(root, 'data/test-tmp/browser-j')}});
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
    for (const [width, height] of [[1366, 768], [1440, 900], [390, 844]]) {
      await page.setViewportSize({width, height});
      await page.screenshot({path: resolve(process.env.LAUNCHER_SCREENSHOT_DIR, `launcher-${width}.png`), fullPage: true});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (width > 800) {
        const action = await page.getByRole('button', {name: '开启陪伴'}).boundingBox();
        expect(action && action.y + action.height <= height).toBeTruthy();
      }
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
  await page.getByText('记忆', {exact: true}).click();
  await expect(page.getByLabel('记忆召回')).toBeVisible();
  await page.getByText('语音', {exact: true}).click();
  await expect(page.getByLabel('聆听环境')).toBeVisible();
  await page.getByText('常用', {exact: true}).click();
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

test('独立圆屏端口及自动IP设置在窄屏可操作，保存不启动服务', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.goto(`${origin}/#token=${token}`);
  const actions: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/api/launcher/actions')) actions.push(request.postData() ?? '');
  });
  await page.getByRole('button', {name: /启动设置/}).click();
  await page.getByLabel('圆屏语音端口').fill('18000');
  await page.getByLabel('圆屏 OTA 端口').fill('18003');
  await page.getByLabel('自动跟踪电脑 IP').click();
  await expect(page.getByLabel('圆屏语音端口')).toHaveValue('18000');
  await expect(page.getByLabel('圆屏 OTA 端口')).toHaveValue('18003');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  if (process.env.LAUNCHER_SCREENSHOT_DIR) {
    await page.screenshot({path: resolve(process.env.LAUNCHER_SCREENSHOT_DIR, 'network-settings-390.png'), fullPage: true});
  }
  await page.getByRole('button', {name: '保存设置'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('button', {name: /启动设置/}).click();
  await expect(page.getByLabel('圆屏语音端口')).toHaveValue('18000');
  await expect(page.getByLabel('自动跟踪电脑 IP')).toHaveAttribute('aria-checked', 'true');
  expect(actions).toEqual([]);
});

test('持续光效可关闭，放大字号与键盘切换保留草稿和焦点', async ({page}) => {
  await page.setViewportSize({width: 1366, height: 768});
  await page.goto(`${origin}/#token=${token}`);
  await expect(page.getByRole('button', {name: '开启陪伴'})).toBeEnabled();
  const control = page.getByRole('button', {name: '持续光效'});
  await control.click();
  await expect(control).toHaveAttribute('aria-pressed', 'false');
  expect(await page.locator('.track-top i').evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  await page.goto('about:blank');
  // 控制令牌只驻留内存，重新打开时从入口注入合成能力令牌。
  await page.goto(`${origin}/#token=${token}`);
  await expect(control).toHaveAttribute('aria-pressed', 'false');
  await page.evaluate(() => {document.documentElement.style.fontSize = '200%';});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', {name: /启动设置/}).click();
  const ip = page.getByLabel('电脑局域网 IP');
  await ip.fill('192.168.1.44');
  const memory = page.getByRole('radio', {name: '记忆'});
  await memory.focus(); await page.keyboard.press('Space');
  await expect(page.getByLabel('记忆召回')).toBeVisible();
  expect(await page.locator('.transition-surface').evaluate(el => el.getAnimations().length)).toBe(0);
  await page.getByText('常用', {exact: true}).click();
  await expect(ip).toHaveValue('192.168.1.44');
  if (process.env.LAUNCHER_SCREENSHOT_DIR) await page.screenshot({path: resolve(process.env.LAUNCHER_SCREENSHOT_DIR, 'launcher-large-reading.png'), fullPage: true});
});

test('装饰无输入焦点，循环只改变合成属性并记录浏览器帧间隔', async ({page}) => {
  await page.goto(`${origin}/#token=${token}`);
  await expect(page.getByRole('button', {name: '开启陪伴'})).toBeEnabled();
  const control = page.getByRole('button', {name: '持续光效'});
  if (await control.getAttribute('aria-pressed') === 'false') await control.click();
  await expect(page.locator('.digital-atmosphere')).toHaveAttribute('aria-hidden', 'true');
  expect(await page.locator('.digital-atmosphere').evaluate(el => getComputedStyle(el).pointerEvents)).toBe('none');
  expect(await page.locator('.digital-atmosphere button,.digital-atmosphere [tabindex]').count()).toBe(0);
  const report = await page.evaluate(async () => {
    const keys = Array.from(document.querySelectorAll('.digital-atmosphere *,.state-core *')).flatMap(el => el.getAnimations()).flatMap(animation =>
      (animation.effect as KeyframeEffect).getKeyframes().flatMap(frame => Object.keys(frame)));
    const unsupported = [...new Set(keys)].filter(key => !['offset', 'computedOffset', 'easing', 'composite', 'transform', 'opacity'].includes(key));
    const frames: number[] = [];
    await new Promise<void>(done => {
      let previous = 0; const start = performance.now();
      const tick = (now: number) => {if (previous) frames.push(now - previous); previous = now;
        if (now - start < 1200) requestAnimationFrame(tick); else done();};
      requestAnimationFrame(tick);
    });
    return {unsupported, frameCount: frames.length, maxFrameMs: Math.max(...frames), over50ms: frames.filter(ms => ms > 50).length};
  });
  expect(report.unsupported).toEqual([]);
  // 帧时间记录实际机器结果，不使用无来源的 FPS 或跨机器硬阈值。
  if (process.env.LAUNCHER_SCREENSHOT_DIR) await writeFile(resolve(process.env.LAUNCHER_SCREENSHOT_DIR, 'motion-performance.json'), JSON.stringify(report, null, 2));
});


test('Cosy交付方式显式保存后重新打开仍保留，不启动服务', async ({page}) => {
  const actions: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/api/launcher/actions')) actions.push(request.postData() ?? '');
  });
  await page.goto(`${origin}/#token=${token}`);
  await page.getByRole('button', {name: /启动设置/}).click();
  await page.getByText('语音', {exact: true}).click();
  await expect(page.getByLabel('声音交付方式')).toBeEnabled();
  await page.getByLabel('声音交付方式').click();
  await page.locator('.ant-select-item-option-content').filter({hasText: /^分段播放（候选）$/}).click();
  await page.getByRole('button', {name: '保存设置'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.goto(`${origin}/#token=${token}`);
  await page.getByRole('button', {name: /启动设置/}).click();
  await page.getByText('语音', {exact: true}).click();
  await expect(page.locator('.launcher-field').filter({has: page.getByLabel('声音交付方式')})).toContainText('分段播放（候选）');
  expect(actions).toEqual([]);
});
