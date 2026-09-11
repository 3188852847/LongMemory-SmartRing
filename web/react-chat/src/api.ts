// 兼容出口：页面可以渐进迁移到领域路径，既有导入无需一次性改写。
export {ApiError, ChatApi} from './api/client';
export type * from './api/types/chat';
export type * from './api/types/device';
export type * from './api/types/memory';
export type * from './api/types/proactive';
export type * from './api/types/settings';
export type * from './api/types/voice';
