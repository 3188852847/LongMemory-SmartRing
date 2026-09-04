import { defineConfig } from 'vite';
// 独立资源前缀；生产服务不公开开发源文件，也不需要常驻 Node。
export default defineConfig({base: '/react-chat/', build: {manifest: true}});
