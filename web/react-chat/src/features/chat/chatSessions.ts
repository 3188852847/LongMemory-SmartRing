import type {Summary} from '../../api';

const MAX_PINNED_CHATS = 100;

/** 置顶属于当前浏览器的整理偏好；只保存会话 ID，不复制聊天正文。 */
export function readPinnedChats(storage: Pick<Storage, 'getItem'>, key: string): string[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(key) ?? '[]');
    if (!Array.isArray(value)) return [];
    return [...new Set(value.filter((item): item is string => typeof item === 'string' && item.length <= 128))]
      .slice(0, MAX_PINNED_CHATS);
  } catch {
    return [];
  }
}

export function writePinnedChats(storage: Pick<Storage, 'setItem'>, key: string, ids: string[]): boolean {
  try {
    storage.setItem(key, JSON.stringify([...new Set(ids)].slice(0, MAX_PINNED_CHATS)));
    return true;
  } catch {
    return false;
  }
}

export function togglePinnedChat(ids: string[], chatId: string): string[] {
  return ids.includes(chatId) ? ids.filter(id => id !== chatId) : [chatId, ...ids];
}

export function organizeChats(chats: Summary[], pinnedIds: string[], query: string): Summary[] {
  const needle = query.trim().toLocaleLowerCase();
  const pinOrder = new Map(pinnedIds.map((id, index) => [id, index]));
  return chats
    .filter(chat => !needle || chat.title.toLocaleLowerCase().includes(needle))
    .map((chat, index) => ({chat, index, pin: pinOrder.get(chat.chat_id)}))
    .sort((left, right) => {
      if (left.pin !== undefined || right.pin !== undefined) {
        if (left.pin === undefined) return 1;
        if (right.pin === undefined) return -1;
        return left.pin - right.pin;
      }
      return left.index - right.index;
    })
    .map(item => item.chat);
}
