export const roundObservationStates = ['idle', 'listening', 'thinking', 'speaking', 'error'] as const;
export type RoundObservationState = typeof roundObservationStates[number];
export type RoundObservationEntry = {observed_at: string; note: string};
export type RoundObservations = Partial<Record<RoundObservationState, RoundObservationEntry>>;

const prefix = 'longmemory:round-display-observations:v1';

export function roundObservationKey(skinId: string, manifestSha256: string) {
  return `${prefix}:${skinId}:${manifestSha256}`;
}

/** 人工视觉观察只保存在当前浏览器；损坏或旧格式数据直接降级为空记录。 */
export function readRoundObservations(storage: Pick<Storage, 'getItem'>, key: string): RoundObservations {
  try {
    const raw = JSON.parse(storage.getItem(key) ?? '{}') as unknown;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    const result: RoundObservations = {};
    for (const state of roundObservationStates) {
      const entry = (raw as Record<string, unknown>)[state];
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
      const value = entry as Record<string, unknown>;
      if (typeof value.observed_at !== 'string' || typeof value.note !== 'string') continue;
      result[state] = {observed_at:value.observed_at, note:value.note.slice(0, 160)};
    }
    return result;
  } catch {
    return {};
  }
}

export function writeRoundObservations(storage: Pick<Storage, 'setItem'>, key: string, value: RoundObservations) {
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
