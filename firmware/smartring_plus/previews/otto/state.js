/* 纯预览仲裁器：事件名为本地演示键，不新增设备协议。 */
(function (root) {
  const states = {
    idle: ['待机', 'neutral'], connecting: ['连接中', 'neutral'],
    listening: ['聆听', 'neutral'], thinking: ['思考', 'thinking'],
    speaking: ['说话', 'neutral'], interrupted: ['被打断', 'surprised'],
    error: ['错误', 'confused'], disconnected: ['已断线', 'sad']
  };
  const names = 'neutral happy laughing funny sad angry crying loving embarrassed surprised shocked thinking winking cool relaxed delicious kissy confident sleepy silly confused'.split(' ');
  function initial() { return { state: 'idle', emotion: 'neutral', deadline: 0, turn: 0, emotionTurn: -1, fault: null }; }
  function step(current, event, now) {
    const s = { ...current };
    if (event.type === 'reset') return initial();
    if (event.type === 'disconnect' || event.type === 'error') {
      s.fault = event.type === 'error' ? 'error' : 'disconnected'; s.state = s.fault;
      s.emotion = 'neutral'; s.emotionTurn = -1; s.deadline = 0; return s;
    }
    if (event.type === 'recover') return initial();
    if (s.fault) return s;
    if (event.type === 'tick') {
      if (s.deadline && now >= s.deadline) {
        if (s.state === 'interrupted') { s.state = 'listening'; s.deadline = 0; }
        else if (s.state === 'thinking' || s.state === 'connecting') { s.state = 'error'; s.fault = 'error'; s.deadline = 0; }
      }
      return s;
    }
    if (event.type === 'emotion') {
      // 不把晚到的说话情绪放到聆听脸上；仅缓存当前轮供 TTS 开始使用。
      if (s.state === 'thinking' || s.state === 'speaking') {
        s.emotion = names.includes(event.name) ? event.name : 'neutral'; s.emotionTurn = s.turn;
      }
      return s;
    }
    if (event.type === 'connect') { s.state = 'connecting'; s.deadline = now + 15000; }
    if (event.type === 'idle') { s.state = 'idle'; s.deadline = 0; s.emotion = 'neutral'; s.emotionTurn = -1; }
    if (event.type === 'listen' || (event.type === 'interrupt' && s.state === 'speaking')) {
      s.turn++; s.emotion = 'neutral'; s.emotionTurn = -1;
      s.state = event.type === 'interrupt' ? 'interrupted' : 'listening';
      s.deadline = event.type === 'interrupt' ? now + 650 : 0;
    }
    if (event.type === 'stt' && s.state === 'listening') { s.state = 'thinking'; s.deadline = now + 20000; }
    if (event.type === 'tts.start' && (s.state === 'thinking' || s.state === 'listening' || s.state === 'idle')) {
      s.state = 'speaking'; s.deadline = 0;
    }
    if (event.type === 'tts.stop' && s.state === 'speaking') {
      s.state = 'listening'; s.turn++; s.deadline = 0; s.emotion = 'neutral'; s.emotionTurn = -1;
    }
    return s;
  }
  function face(s) { return s.state === 'speaking' && s.emotionTurn === s.turn ? s.emotion : states[s.state][1]; }
  const api = { states, names, initial, step, face };
  if (typeof module !== 'undefined') module.exports = api;
  else root.OttoState = api;
})(typeof window !== 'undefined' ? window : globalThis);
