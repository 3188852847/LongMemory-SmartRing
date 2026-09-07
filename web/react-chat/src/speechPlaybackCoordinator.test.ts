import {afterEach, describe, expect, test, vi} from 'vitest';
import {claimSpeechPlayback, stopActiveSpeechPlayback} from './speechPlaybackCoordinator';

describe('网页朗读协调器', () => {
  afterEach(() => stopActiveSpeechPlayback());

  test('新朗读会停止上一条，旧释放函数不会误清除新租约', () => {
    const first = vi.fn();
    const second = vi.fn();
    const releaseFirst = claimSpeechPlayback(first);
    claimSpeechPlayback(second);
    expect(first).toHaveBeenCalledOnce();
    releaseFirst();
    stopActiveSpeechPlayback();
    expect(second).toHaveBeenCalledOnce();
  });
});
