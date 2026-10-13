// 控制台 API 统一出口；按领域组织传输类型，页面与功能通过这里调用服务。
export {ApiError, ChatApi} from './client';
export type * from './types/chat';
export type * from './types/device';
export type * from './types/memory';
export type * from './types/proactive';
export type * from './types/settings';
export type * from './types/voice';
