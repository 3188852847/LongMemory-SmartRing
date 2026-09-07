type ActivePlayback = {token: symbol; stop: () => void};

let active: ActivePlayback | undefined;

/** 浏览器同一时间只允许一条网页朗读占用扬声器和可选麦克风。 */
export function claimSpeechPlayback(stopPrevious: () => void): () => void {
  const previous = active;
  active = undefined;
  previous?.stop();
  const token = Symbol('speech-playback');
  active = {token, stop: stopPrevious};
  return () => {
    if (active?.token === token) active = undefined;
  };
}

export function stopActiveSpeechPlayback() {
  const current = active;
  active = undefined;
  current?.stop();
}
