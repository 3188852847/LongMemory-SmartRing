import type {Turn} from '../../api';

export type DialogueMessage = {
  id: string; role: 'user' | 'assistant'; text: string; at: string; channel: string; proactive: boolean;
};
export type SharedDialogue = {enabled: boolean; messages: DialogueMessage[]};

type ChatEntry = {key: string; at: number} & (
  | {kind: 'shared'; message: DialogueMessage}
  | {kind: 'user' | 'assistant'; turn: Turn; index: number}
);

/** 同一条网页消息有会话档案和共享记录两种表示，优先保留可查看证据的会话档案。 */
export function mergeDialogue(turns: Turn[], shared: DialogueMessage[]): ChatEntry[] {
  const sharedById = new Map(shared.map(message => [message.id, message]));
  const entries: ChatEntry[] = [];
  turns.forEach((turn, index) => {
    const started = typeof turn.started_at === 'string' ? Date.parse(turn.started_at) : NaN;
    for (const kind of ['user', 'assistant'] as const) {
      const id = kind === 'user' ? turn.event_id : turn.assistant_event_id;
      const source = typeof id === 'string' ? sharedById.get(id) : undefined;
      if (source) sharedById.delete(source.id);
      const at = source ? Date.parse(source.at) : started + (kind === 'assistant' ? turn.duration_ms : 0);
      entries.push({key: `turn-${turn.request_id ?? index}-${kind}`, at: Number.isFinite(at) ? at : 0, kind, turn, index});
    }
  });
  for (const message of sharedById.values()) {
    entries.push({key: message.id, at: Date.parse(message.at), kind: 'shared', message});
  }
  return entries.sort((a, b) => a.at - b.at);
}

export function dialogueLabel(channel: string, proactive: boolean) {
  const label = ({web: '网页', qq: 'QQ', screen: '圆屏'} as Record<string, string>)[channel] ?? channel;
  return proactive ? `${label} · 主动联系` : label;
}
