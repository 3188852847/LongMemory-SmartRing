import type {Page} from '@playwright/test';
import {KEY} from '../../assets/appearance.mjs';

/** 使用真实偏好入口与 Provider 监听，刷新后仍是大字号；不只临时改 DOM。 */
export async function largerReading(page:Page){
  await page.evaluate(key=>{
    localStorage.setItem(key,JSON.stringify({theme:'future',size:'larger',motion:'reduce',density:'comfortable',chatWidth:'focused'}));
    window.dispatchEvent(new StorageEvent('storage',{key}));
  },KEY);
}
