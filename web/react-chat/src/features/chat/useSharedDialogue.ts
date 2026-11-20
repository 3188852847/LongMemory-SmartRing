import {useEffect, useRef, useState} from 'react';
import {replaceEqualDeep, useInfiniteQuery, useQuery} from '@tanstack/react-query';
import {ChatApi} from '../../api';
import type {DialogueMessage, SharedDialogue} from './sharedDialogue';

const PAGE_SIZE = 60;
type Page = {messages: DialogueMessage[]; before: string | null};

export function useSharedDialogue(api: ChatApi, database: string | undefined, chatId: string | undefined, active: boolean) {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  const browsing = useRef<string | undefined>(undefined);
  useEffect(() => {browsing.current = undefined;}, [chatId]);
  const latest = useQuery({
    queryKey: ['companion-dialogue', database, chatId],
    enabled: Boolean(chatId && database && visible),
    queryFn: () => api.request<SharedDialogue>('/api/companion/dialogue' + (active && !document.hidden ? '?active=1' : '')),
    structuralSharing: (previous: unknown, next: unknown) => {
      const first = previous as SharedDialogue | undefined;
      const last = next as SharedDialogue;
      if (browsing.current === chatId && first?.enabled && last.enabled) {
        const byId = new Map(first.messages.map(message => [message.id, message]));
        for (const message of last.messages) byId.set(message.id, message);
        return replaceEqualDeep(first, {...last, messages: Array.from(byId.values())});
      }
      return replaceEqualDeep(previous, next);
    },
    refetchInterval: 5000, refetchIntervalInBackground: false, retry: false, gcTime: 0,
  });
  const head = latest.data?.enabled ? latest.data.messages : [];
  const earlier = useInfiniteQuery({
    queryKey: ['companion-dialogue-earlier', database, chatId],
    initialPageParam: null as string | null,
    queryFn: async ({pageParam}): Promise<Page> => {
      // 首次翻页时固定当时的整页，轮询窗口后移时仍与前一页连续。
      const boundary = pageParam ?? head[0]?.id;
      if (!boundary) return {messages: [], before: null};
      const url = '/api/companion/dialogue?' + new URLSearchParams({before: boundary, limit: String(PAGE_SIZE)});
      const {messages} = await api.request<SharedDialogue>(url);
      return {messages: pageParam ? messages : [...messages, ...head],
        before: messages.length === PAGE_SIZE ? messages[0].id : null};
    },
    getNextPageParam: last => last.before ?? undefined,
    enabled: false, retry: false, staleTime: Infinity, gcTime: 0,
  });
  const pages = earlier.data?.pages ?? [];
  const messages = pages.slice().reverse().flatMap(page => page.messages).concat(head);
  return {
    messages: latest.data?.enabled ? messages : [],
    failed: latest.isError,
    canReadEarlier: latest.data?.enabled && (pages.length ? earlier.hasNextPage : head.length >= PAGE_SIZE),
    readingEarlier: earlier.isFetching,
    earlierFailed: earlier.isError,
    readEarlier: () => {
      browsing.current = chatId;
      return earlier.fetchNextPage({cancelRefetch:false});
    },
    oldestPage: pages.at(-1),
  };
}
