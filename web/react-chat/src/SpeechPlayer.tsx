import {useEffect, useRef, useState} from 'react';
import {Button, Space, Switch} from 'antd';
import {Link} from 'react-router-dom';
import {ApiError, ChatApi} from './api';
import {claimSpeechPlayback} from './speechPlaybackCoordinator';

export function speechFailure(error:unknown) {
  if (!(error instanceof ApiError)) return {text:'朗读请求未完成。请检查本机网页服务，未自动重试。', settings:false};
  const messages:Record<string,string> = {
    speech_busy:'已有一条语音正在生成，请稍后手动重试。',
    tts_service_unavailable:'当前 TTS 服务没有就绪或本次合成失败。请核对声音设置和统一启动面板。',
    tts_backend_unsupported:'当前 TTS 配置不受网页朗读支持，请在声音设置中核对后端。',
    voice_environment_unavailable:'小智声音环境不完整或不可访问，请核对声音设置中的环境状态。',
    tts_config_unavailable:'无法读取当前小智 TTS 配置，请核对共享路径和声音设置。',
    speech_failed:'朗读生成失败，服务没有返回可播放音频。未自动重试。',
  };
  return {text:messages[error.code]??messages.speech_failed, settings:error.code!=='speech_busy'};
}

/** 浏览器返回的 DOMException 文案会因浏览器和系统语言变化，不应直接成为产品提示。 */
export function microphoneFailure(error: unknown) {
  const name = error instanceof DOMException ? error.name : '';
  const messages: Record<string, string> = {
    NotAllowedError: '麦克风权限未授予。请在浏览器地址栏的网站权限中允许麦克风后再开启说话打断。',
    SecurityError: '浏览器因安全策略阻止了麦克风访问。请核对当前页面权限后再试。',
    NotFoundError: '没有找到可用麦克风。请连接或启用麦克风后再开启说话打断。',
    DevicesNotFoundError: '没有找到可用麦克风。请连接或启用麦克风后再开启说话打断。',
    NotReadableError: '麦克风当前不可用，可能正被其他程序独占。关闭占用程序后再试。',
    TrackStartError: '麦克风当前不可用，可能正被其他程序独占。关闭占用程序后再试。',
    AbortError: '麦克风启动被系统中断。请确认设备仍已连接后手动重试。',
  };
  return messages[name] ?? '无法启用麦克风打断。请检查浏览器权限和系统输入设备后手动重试。';
}

/** 网页朗读只在电脑播放；麦克风仅在播放监听期间用于本地音量判断，不上传录音。 */
export function SpeechPlayer({api, text}: {api: ChatApi; text: string}) {
  const audio = useRef<HTMLAudioElement | undefined>(undefined);
  const objectUrl = useRef<string | undefined>(undefined);
  const stream = useRef<MediaStream | undefined>(undefined);
  const audioContext = useRef<AudioContext | undefined>(undefined);
  const frame = useRef(0);
  const requestGeneration = useRef(0);
  const releasePlaybackLease = useRef<() => void>(() => undefined);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [generationMs, setGenerationMs] = useState<number | null>(null);
  const [settingsHint,setSettingsHint] = useState(false);
  const [speechInterrupt, setSpeechInterrupt] = useState(false);

  const releaseAudioUrl = () => {
    if (!objectUrl.current) return;
    URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = undefined;
  };

  const releaseMicrophone = () => {
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = undefined;
    if (audioContext.current) void audioContext.current.close();
    audioContext.current = undefined;
  };

  const stopPlayback = () => {
    if (audio.current) {
      audio.current.pause();
      audio.current.currentTime = 0;
      audio.current = undefined;
    }
    releaseMicrophone();
    releaseAudioUrl();
    releasePlaybackLease.current();
    releasePlaybackLease.current = () => undefined;
  };

  const stop = () => {
    // 即使音频还在服务端生成，也要使这次结果失效，避免稍后突然开始播放。
    requestGeneration.current += 1;
    stopPlayback();
    setSettingsHint(false);
    setNotice('已停止网页朗读，麦克风已释放。');
  };

  useEffect(() => () => {
    requestGeneration.current += 1;
    stopPlayback();
  }, []);

  async function openMicrophone() {
    if (stream.current) return stream.current;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('当前浏览器不支持麦克风打断测试。');
    }
    stream.current = await navigator.mediaDevices.getUserMedia({
      audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
    });
    return stream.current;
  }

  async function checkMicrophonePermission() {
    await openMicrophone();
    // 开关只表示下次朗读要启用打断，不应在待机时持续占用麦克风。
    releaseMicrophone();
  }

  async function monitor() {
    const media = await openMicrophone();
    const context = new AudioContext();
    audioContext.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(media).connect(analyser);
    const values = new Uint8Array(analyser.fftSize);
    let loudFrames = 0;

    const tick = () => {
      if (!audio.current || audio.current.paused) {
        releaseMicrophone();
        return;
      }
      analyser.getByteTimeDomainData(values);
      let energy = 0;
      for (const value of values) {
        const centered = (value - 128) / 128;
        energy += centered * centered;
      }
      const rms = Math.sqrt(energy / values.length);
      loudFrames = rms > 0.07 ? loudFrames + 1 : 0;
      if (loudFrames >= 4) {
        stopPlayback();
        setNotice('检测到你说话，已打断网页朗读并释放麦克风。');
        return;
      }
      frame.current = requestAnimationFrame(tick);
    };
    tick();
  }

  async function play() {
    if (busy) return;
    const request = ++requestGeneration.current;
    setBusy(true);
    setGenerationMs(null);
    setSettingsHint(false);
    setNotice('正在生成朗读…');
    const startedAt = performance.now();
    try {
      const blob = await api.speech(text);
      if (request !== requestGeneration.current) return;
      setGenerationMs(Math.max(0, performance.now() - startedAt));
      stopPlayback();
      const url = URL.createObjectURL(blob);
      objectUrl.current = url;
      releasePlaybackLease.current = claimSpeechPlayback(() => {
        stopPlayback();
        setNotice('另一条网页朗读已开始，本条已停止并释放麦克风。');
      });
      const element = new Audio(url);
      audio.current = element;
      element.onended = () => {
        audio.current = undefined;
        releaseMicrophone();
        releaseAudioUrl();
        releasePlaybackLease.current();
        releasePlaybackLease.current = () => undefined;
        setNotice('朗读完成，麦克风已释放。');
      };
      element.onerror = () => {
        audio.current = undefined;
        releaseMicrophone();
        releaseAudioUrl();
        releasePlaybackLease.current();
        releasePlaybackLease.current = () => undefined;
        setNotice('浏览器无法播放生成的音频。');
      };
      await element.play();
      setNotice('正在电脑播放；这不会驱动圆屏。');
      if (speechInterrupt) {
        void monitor().catch(error => {
          releaseMicrophone();
          setNotice(microphoneFailure(error));
        });
      }
    } catch (error) {
      if (request !== requestGeneration.current) return;
      stopPlayback();
      const failure=speechFailure(error);setNotice(failure.text);setSettingsHint(failure.settings);
    } finally {
      setBusy(false);
    }
  }

  async function changeSpeechInterrupt(value: boolean) {
    setSettingsHint(false);
    if (!value) {
      setSpeechInterrupt(false);
      releaseMicrophone();
      setNotice('说话打断已关闭，麦克风已释放。');
      return;
    }
    try {
      await checkMicrophonePermission();
      setSpeechInterrupt(true);
      setNotice('说话打断已开启；麦克风只会在朗读期间启用。');
    } catch (error) {
      releaseMicrophone();
      setNotice(microphoneFailure(error));
    }
  }

  return <div className="speech-player">
    <Space wrap>
      <Button size="small" loading={busy} onClick={() => void play()}>网页朗读</Button>
      <Button size="small" onClick={stop}>停止</Button>
      <span>说话打断</span>
      <Switch size="small" checked={speechInterrupt} onChange={value => void changeSpeechInterrupt(value)}/>
    </Space>
    {notice && <small role="status">{notice}{settingsHint&&<> <Link to="/settings?tab=voice">打开声音设置</Link></>}</small>}
    {generationMs !== null && <small className="speech-generation-time">最近一次网页合成等待：{(generationMs / 1000).toFixed(2)} 秒（含本机接口与音频返回，不代表圆屏首句延迟）</small>}
  </div>;
}
