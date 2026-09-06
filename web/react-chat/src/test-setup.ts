import {afterEach} from 'vitest';
import {cleanup} from '@testing-library/react';

afterEach(() => cleanup());

// jsdom 不实现媒体查询；提供最小浏览器契约，让 antd 响应式逻辑可被组件测试加载。
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  }),
});
