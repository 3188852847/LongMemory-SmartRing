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

// antd 的表格会查询伪元素样式；jsdom 尚未实现第二参数，测试中忽略它即可。
const computedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (element: Element) => computedStyle(element);

class TestResizeObserver implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(window, 'ResizeObserver', {writable:true, value:TestResizeObserver});
Object.defineProperty(globalThis, 'ResizeObserver', {writable:true, value:TestResizeObserver});
