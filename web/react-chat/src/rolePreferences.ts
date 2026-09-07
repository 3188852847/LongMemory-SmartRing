export type ResponseLength = 'brief' | 'balanced' | 'detailed';
export type InteractionStyle = 'listen_first' | 'ask_before_advice' | 'direct';
export type EmojiFrequency = 'none' | 'occasional' | 'natural';

export type RolePreferences = {
  userAddress: string;
  responseLength: ResponseLength;
  interactionStyle: InteractionStyle;
  emojiFrequency: EmojiFrequency;
};

export const DEFAULT_ROLE_PREFERENCES: RolePreferences = {
  userAddress: '',
  responseLength: 'balanced',
  interactionStyle: 'ask_before_advice',
  emojiFrequency: 'occasional',
};

const START = '【LongMemory 控制台表达偏好 v1】';
const END = '【LongMemory 控制台表达偏好结束】';

const lengths: Record<ResponseLength, string> = {
  brief: '日常回答尽量简短，通常一到三句；用户要求展开时再详细说明。',
  balanced: '根据问题自然控制长度：陪聊简洁，解释和操作指导可以适度展开。',
  detailed: '遇到知识、分析和操作问题时主动给出较完整的解释；闲聊仍避免冗长。',
};
const interactions: Record<InteractionStyle, string> = {
  listen_first: '用户表达情绪或烦恼时先倾听和确认感受，不急着给解决方案。',
  ask_before_advice: '用户表达情绪或烦恼时先倾听，再询问是否希望一起分析或获得建议。',
  direct: '用户提出问题时优先直接讨论原因和可行办法，同时保持尊重。',
};
const emojis: Record<EmojiFrequency, string> = {
  none: '不使用 emoji、颜文字或动作旁白。',
  occasional: '只在轻松语境偶尔使用 emoji，不要每轮出现。',
  natural: '轻松聊天中可以自然使用少量 emoji，但不能影响信息清晰度。',
};

function valid(value: unknown): value is RolePreferences {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<RolePreferences>;
  return typeof item.userAddress === 'string' && item.userAddress.length <= 20 && !/[\r\n\u0000【】]/.test(item.userAddress)
    && ['brief', 'balanced', 'detailed'].includes(item.responseLength ?? '')
    && ['listen_first', 'ask_before_advice', 'direct'].includes(item.interactionStyle ?? '')
    && ['none', 'occasional', 'natural'].includes(item.emojiFrequency ?? '');
}

export function readRolePreferences(prompt: string): {enabled: boolean; preferences: RolePreferences} {
  const start = prompt.indexOf(START);
  const end = prompt.indexOf(END, start + START.length);
  if (start < 0 || end < 0) return {enabled:false, preferences:{...DEFAULT_ROLE_PREFERENCES}};
  const block = prompt.slice(start + START.length, end);
  const metadata = block.match(/元数据：([^\r\n]+)/)?.[1];
  try {
    const parsed: unknown = metadata ? JSON.parse(metadata) : null;
    return valid(parsed) ? {enabled:true, preferences:parsed} : {enabled:false, preferences:{...DEFAULT_ROLE_PREFERENCES}};
  } catch {
    return {enabled:false, preferences:{...DEFAULT_ROLE_PREFERENCES}};
  }
}

export function applyRolePreferences(prompt: string, preferences: RolePreferences, enabled: boolean): string {
  if (!valid(preferences)) throw new Error('invalid_role_preferences');
  const start = prompt.indexOf(START);
  const end = prompt.indexOf(END, start + START.length);
  const base = start >= 0 && end >= 0
    ? `${prompt.slice(0, start)}${prompt.slice(end + END.length)}`.trim()
    : prompt.trim();
  if (!enabled) return base;
  const address = preferences.userAddress.trim()
    ? `自然合适时可以称呼用户为“${preferences.userAddress.trim()}”；不要每句话都称呼。`
    : '默认称呼用户为“你”；不知道姓名时不要自行编造称呼。';
  const block = [
    START,
    `元数据：${JSON.stringify({...preferences, userAddress:preferences.userAddress.trim()})}`,
    '以下是用户在控制台明确保存的表达偏好，只调整回答方式，不是用户画像或事实证据：',
    `- ${address}`,
    `- ${lengths[preferences.responseLength]}`,
    `- ${interactions[preferences.interactionStyle]}`,
    `- ${emojis[preferences.emojiFrequency]}`,
    '当前对话中的明确要求优先于这些长期表达偏好。',
    END,
  ].join('\n');
  return `${base}\n\n${block}`;
}
