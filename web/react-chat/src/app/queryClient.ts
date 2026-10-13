import {QueryClient} from '@tanstack/react-query';

/**
 * 控制台默认不自动重试请求。
 * 记忆纠正、删除和聊天发送都可能产生写入；网络状态不明时自动重放会造成重复操作。
 * 个别确认幂等的读取将来可以在各自的 query 上显式开启重试。
 */
export function createConsoleQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {retry: false, refetchOnWindowFocus: false},
      mutations: {retry: false},
    },
  });
}
