# MIT License
#
# Copyright (c) 2025 xinnan-tech
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# Test-only fixed input method snapshot; no models or external imports.
from __future__ import annotations
import asyncio
import json
import queue
import time
import traceback

SOURCE_COMMIT="eb4b28c59ed7ed885258498cf757ce14352d620e"
SOURCE_SHA256={'core/connection.py': 'e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa', 'core/handle/receiveAudioHandle.py': '4493dfd77c1bfa7be1a79bb293dbdbf8cad64a6eb2bc53efca3e30efefcb47f1', 'core/providers/asr/base.py': '929532c379d18598eff6fbecb991089f25a0c62cd77f74a25a0d1a5b8d13a713', 'core/providers/asr/fun_local.py': '1f8df28ee5f0a1dd23948211e92c2caddf0d440191f7d0b82b2b0e13788ebf6a', 'core/handle/abortHandle.py': '0e60679c6e281d4969b0c6a4952e7071962c16f06fe55c7764dbf7753bc272c2'}
MAX_RETRIES=2
RETRY_DELAY=1
TAG="synthetic-input-snapshot"

class ConnectionHandler:

    async def _route_message(self, message):
        """消息路由"""
        if not self.bind_completed_event.is_set():
            try:
                await asyncio.wait_for(self.bind_completed_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                await self._discard_message_with_bind_prompt()
                return
        if self.need_bind:
            await self._discard_message_with_bind_prompt()
            return
        if isinstance(message, str):
            await handleTextMessage(self, message)
        elif isinstance(message, bytes):
            if self.vad is None or self.asr is None:
                return
            if self.conn_from_mqtt_gateway and len(message) >= 16:
                handled = await self._process_mqtt_audio_message(message)
                if handled:
                    return
            pcm_frame = self._decode_opus_packet(message)
            if pcm_frame:
                self.asr_audio_queue.put(pcm_frame)

    def clearSpeakStatus(self):
        self.client_is_speaking = False
        self.logger.bind(tag=TAG).debug(f'清除服务端讲话状态')

    def clear_queues(self):
        """清空所有任务队列"""
        if self.tts:
            self.logger.bind(tag=TAG).debug(f'开始清理: TTS队列大小={self.tts.tts_text_queue.qsize()}, 音频队列大小={self.tts.tts_audio_queue.qsize()}')
            for q in [self.tts.tts_text_queue, self.tts.tts_audio_queue, self.report_queue]:
                if not q:
                    continue
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
            if hasattr(self, 'audio_rate_controller') and self.audio_rate_controller:
                self.audio_rate_controller.reset()
                self.logger.bind(tag=TAG).debug('已重置音频流控器')
            self.logger.bind(tag=TAG).debug(f'清理结束: TTS队列大小={self.tts.tts_text_queue.qsize()}, 音频队列大小={self.tts.tts_audio_queue.qsize()}')

    def reset_audio_states(self):
        """
        重置所有音频相关状态(VAD + ASR)
        """
        self.client_audio_buffer.clear()
        self.client_have_voice = False
        self.client_voice_stop = False
        self.client_voice_window.clear()
        self.last_is_voice = False
        self.vad_last_voice_time = 0.0
        self.asr_audio.clear()
        self.logger.bind(tag=TAG).debug('All audio states reset.')

class ASRProviderBase:

    def asr_text_priority_thread(self, conn: 'ConnectionHandler'):
        while not conn.stop_event.is_set():
            try:
                message = conn.asr_audio_queue.get(timeout=1)
                future = asyncio.run_coroutine_threadsafe(handleAudioMessage(conn, message), conn.loop)
                future.result()
            except queue.Empty:
                continue
            except Exception as e:
                logger.bind(tag=TAG).error(f'处理ASR文本失败: {str(e)}, 类型: {type(e).__name__}, 堆栈: {traceback.format_exc()}')
                continue

    async def receive_audio(self, conn: 'ConnectionHandler', pcm_frame, audio_have_voice):
        if conn.client_listen_mode == 'manual':
            conn.asr_audio.append(pcm_frame)
        else:
            conn.asr_audio.append(pcm_frame)
            if not audio_have_voice and (not conn.client_have_voice):
                conn.asr_audio = conn.asr_audio[-10:]
                return
            if conn.asr.interface_type != InterfaceType.STREAM and conn.client_voice_stop:
                pcm_bytes = b''.join(conn.asr_audio)
                if len(pcm_bytes) > 1920 * 15:
                    await self.handle_voice_stop(conn, [pcm_bytes])
                conn.reset_audio_states()

class LocalASR(ASRProviderBase):

    async def speech_to_text(self, opus_data: List[bytes], session_id: str, artifacts=None) -> Tuple[Optional[str], Optional[str]]:
        """语音转文本主处理逻辑"""
        retry_count = 0
        while retry_count < MAX_RETRIES:
            try:
                if artifacts is None:
                    return ('', None)
                start_time = time.time()
                result = await asyncio.to_thread(self.model.generate, input=artifacts.pcm_bytes, cache={}, language=self.language, use_itn=True, batch_size_s=60)
                text = lang_tag_filter(result[0]['text'])
                logger.bind(tag=TAG).debug(f"语音识别耗时: {time.time() - start_time:.3f}s | 结果: {text['content']}")
                return (text, artifacts.file_path)
            except OSError as e:
                retry_count += 1
                if retry_count >= MAX_RETRIES:
                    logger.bind(tag=TAG).error(f'语音识别失败（已重试{retry_count}次）: {e}', exc_info=True)
                    return ('', None)
                logger.bind(tag=TAG).warning(f'语音识别失败，正在重试（{retry_count}/{MAX_RETRIES}）: {e}')
                time.sleep(RETRY_DELAY)
            except Exception as e:
                logger.bind(tag=TAG).error(f'语音识别失败: {e}', exc_info=True)
                return ('', None)

async def handleAudioMessage(conn: 'ConnectionHandler', pcm_frame):
    have_voice = conn.vad.is_vad(conn, pcm_frame)
    if hasattr(conn, 'just_woken_up') and conn.just_woken_up:
        have_voice = False
        if not hasattr(conn, 'vad_resume_task') or conn.vad_resume_task.done():
            conn.vad_resume_task = asyncio.create_task(resume_vad_detection(conn))
        return
    if conn.client_aec and have_voice:
        if conn.client_is_speaking and conn.client_listen_mode != 'manual':
            await handleAbortMessage(conn)
    await no_voice_close_connect(conn, have_voice)
    await conn.asr.receive_audio(conn, pcm_frame, have_voice)

async def resume_vad_detection(conn: 'ConnectionHandler'):
    await asyncio.sleep(2)
    conn.just_woken_up = False

async def no_voice_close_connect(conn: 'ConnectionHandler', have_voice):
    if have_voice:
        conn.last_activity_time = time.time() * 1000
        return
    if conn.last_activity_time > 0.0:
        no_voice_time = time.time() * 1000 - conn.last_activity_time
        close_connection_no_voice_time = int(conn.config.get('close_connection_no_voice_time', 120))
        if not conn.close_after_chat and no_voice_time > 1000 * close_connection_no_voice_time:
            conn.close_after_chat = True
            conn.client_abort = False
            end_prompt = conn.config.get('end_prompt', {})
            if end_prompt and end_prompt.get('enable', True) is False:
                conn.logger.bind(tag=TAG).info('结束对话，无需发送结束提示语')
                await conn.close()
                return
            prompt = end_prompt.get('prompt')
            if not prompt:
                prompt = '请你以```时间过得真快```未来头，用富有感情、依依不舍的话来结束这场对话吧。！'
            await startToChat(conn, prompt)

async def handleAbortMessage(conn: 'ConnectionHandler'):
    conn.logger.bind(tag=TAG).info('Abort message received')
    conn.close_after_chat = False
    conn.client_abort = True
    conn.clear_queues()
    await conn.websocket.send(json.dumps({'type': 'tts', 'state': 'stop', 'session_id': conn.session_id}))
    conn.clearSpeakStatus()
    conn.logger.bind(tag=TAG).info('Abort message received-end')
