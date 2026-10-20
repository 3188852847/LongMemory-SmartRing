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
# Test-only method snapshot; native code stays unchanged.
SOURCE_COMMIT = 'eb4b28c59ed7ed885258498cf757ce14352d620e'
SOURCE_FILES = {'main/xiaozhi-server/core/providers/llm/openai/openai.py': {'sha256': '5dfec38041d28436362b4a1b0f5946d1bdff7bb9afb3501c6417037a6bd3b006', 'tracked_file_unmodified': True}, 'main/xiaozhi-server/core/connection.py': {'sha256': 'e065c994bf3f926b81c69da045e09fad8c46d6fd1fc3e3a6403295aeab64e0fa', 'tracked_file_unmodified': True}}

THINKING_DISABLED_DOMAINS = {'aliyuncs.com': {'enable_thinking': False}, 'deepseek.com': {'thinking': {'type': 'disabled'}}, 'bigmodel.cn': {'thinking': {'type': 'disabled'}}, 'moonshot.cn': {'thinking': {'type': 'disabled'}}, 'volces.com': {'thinking': {'type': 'disabled'}}}

class LLMProvider:

    @staticmethod
    def normalize_dialogue(dialogue):
        """自动修复 dialogue 中缺失 content 的消息"""
        for msg in dialogue:
            if 'role' in msg and 'content' not in msg:
                msg['content'] = ''
        return dialogue

    def _apply_thinking_disabled(self, request_params: dict):
        """根据域名自动禁用思考模式"""
        parsed_url = urlparse(self.base_url)
        domain = parsed_url.netloc
        for disabled_domain, params in THINKING_DISABLED_DOMAINS.items():
            if disabled_domain in domain:
                request_params.setdefault('extra_body', {}).update(params)
                logger.bind(tag=TAG).info(f'为域名 {domain} 禁用思考模式，参数: {params}')
                break

    def response(self, session_id, dialogue, **kwargs):
        dialogue = self.normalize_dialogue(dialogue)
        request_params = {'model': self.model_name, 'messages': dialogue, 'stream': True}
        optional_params = {'max_tokens': kwargs.get('max_tokens', self.max_tokens), 'temperature': kwargs.get('temperature', self.temperature), 'top_p': kwargs.get('top_p', self.top_p), 'frequency_penalty': kwargs.get('frequency_penalty', self.frequency_penalty)}
        for key, value in optional_params.items():
            if value is not None:
                request_params[key] = value
        self._apply_thinking_disabled(request_params)
        responses = self.client.chat.completions.create(**request_params)
        is_active = True
        try:
            for chunk in responses:
                try:
                    delta = chunk.choices[0].delta if getattr(chunk, 'choices', None) else None
                    content = getattr(delta, 'content', '') if delta else ''
                except IndexError:
                    content = ''
                if content:
                    if '<think>' in content:
                        is_active = False
                        content = content.split('<think>')[0]
                    if '</think>' in content:
                        is_active = True
                        content = content.split('</think>')[-1]
                    if is_active:
                        yield content
        finally:
            responses.close()

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        dialogue = self.normalize_dialogue(dialogue)
        request_params = {'model': self.model_name, 'messages': dialogue, 'stream': True, 'tools': functions}
        optional_params = {'max_tokens': kwargs.get('max_tokens', self.max_tokens), 'temperature': kwargs.get('temperature', self.temperature), 'top_p': kwargs.get('top_p', self.top_p), 'frequency_penalty': kwargs.get('frequency_penalty', self.frequency_penalty)}
        for key, value in optional_params.items():
            if value is not None:
                request_params[key] = value
        self._apply_thinking_disabled(request_params)
        stream = self.client.chat.completions.create(**request_params)
        try:
            for chunk in stream:
                if getattr(chunk, 'choices', None):
                    delta = chunk.choices[0].delta
                    content = getattr(delta, 'content', '')
                    tool_calls = getattr(delta, 'tool_calls', None)
                    yield (content, tool_calls)
                elif isinstance(getattr(chunk, 'usage', None), CompletionUsage):
                    usage_info = getattr(chunk, 'usage', None)
                    logger.bind(tag=TAG).info(f"Token 消耗：输入 {getattr(usage_info, 'prompt_tokens', '未知')}，输出 {getattr(usage_info, 'completion_tokens', '未知')}，共计 {getattr(usage_info, 'total_tokens', '未知')}")
        finally:
            stream.close()

def chat(self, query, depth=0):
    current_sentence_id = None
    if query is not None:
        self.logger.bind(tag=TAG).info(f'大模型收到用户消息: {query}')
    if depth == 0:
        current_sentence_id = str(uuid.uuid4().hex)
        self.sentence_id = current_sentence_id
        self.dialogue.put(Message(role='user', content=query))
        self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.FIRST, content_type=ContentType.ACTION))
    else:
        current_sentence_id = self.sentence_id
    MAX_DEPTH = 5
    force_final_answer = False
    if depth >= MAX_DEPTH:
        self.logger.bind(tag=TAG).debug(f'已达到最大工具调用深度 {MAX_DEPTH}，将强制基于现有信息回答')
        force_final_answer = True
        self.dialogue.put(Message(role='user', content='[系统提示] 已达到最大工具调用次数限制，请你基于目前已经获取的所有信息，直接给出最终答案。不要再尝试调用任何工具。'))
    functions = None
    if self.intent_type == 'function_call' and hasattr(self, 'func_handler') and (not force_final_answer):
        functions = list(self.func_handler.get_functions())
        if functions is not None and depth == 0:
            functions.append(DIRECT_ANSWER_TOOL)
    response_message = []
    try:
        memory_str = None
        if self.memory is not None and query:
            future = asyncio.run_coroutine_threadsafe(self.memory.query_memory(query), self.loop)
            memory_str = future.result()
        speaker_for_system = None
        cs = (self.current_speaker or '').strip()
        if cs and cs != '未知说话人' and (cs not in self.system_introduced_speakers):
            self.system_introduced_speakers.add(cs)
            speaker_for_system = cs
        if self.intent_type == 'function_call' and functions is not None:
            llm_responses = self.llm.response_with_functions(self.session_id, self.dialogue.get_llm_dialogue_with_memory(memory_str, self.config.get('voiceprint', {}), speaker_for_system), functions=functions)
        else:
            llm_responses = self.llm.response(self.session_id, self.dialogue.get_llm_dialogue_with_memory(memory_str, self.config.get('voiceprint', {}), speaker_for_system))
    except Exception as e:
        self.logger.bind(tag=TAG).error(f'LLM 处理出错 {query}: {e}')
        return None
    tool_call_flag = False
    tool_calls_list = []
    content_arguments = ''
    emotion_flag = True
    try:
        for response in llm_responses:
            if self.client_abort:
                break
            if self.intent_type == 'function_call' and functions is not None:
                content, tools_call = response
                if 'content' in response:
                    content = response['content']
                    tools_call = None
                if content is not None and len(content) > 0:
                    content_arguments += content
                if not tool_call_flag and content_arguments.startswith('<tool_call>'):
                    tool_call_flag = True
                if tools_call is not None and len(tools_call) > 0:
                    tool_call_flag = True
                    self._merge_tool_calls(tool_calls_list, tools_call)
                _DA_STREAM_BUFFER = 5
                for tc in tool_calls_list:
                    if tc['name'] == 'direct_answer' and tc.get('arguments'):
                        da_text = self._extract_direct_answer_response(tc['arguments'])
                        sent_len = tc.get('_da_sent', 0)
                        if da_text and len(da_text) > sent_len:
                            safe_end = max(sent_len, len(da_text) - _DA_STREAM_BUFFER)
                            if safe_end > sent_len:
                                new_part = da_text[sent_len:safe_end]
                                new_part = self._clean_response_garbage(new_part)
                                if new_part:
                                    tc['_da_sent'] = safe_end
                                    self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=new_part))
            else:
                content = response
            if emotion_flag and content is not None and content.strip():
                if (self.features or {}).get('emoji', True):
                    asyncio.run_coroutine_threadsafe(textUtils.get_emotion(self, content), self.loop)
                emotion_flag = False
            if content is not None and len(content) > 0:
                if not tool_call_flag:
                    response_message.append(content)
                    self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=content))
    except Exception as e:
        self.logger.bind(tag=TAG).error(f'LLM stream processing error: {e}')
        self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=get_system_error_response(self.config)))
        if depth == 0:
            self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION))
        return
    if tool_call_flag:
        bHasError = False
        if len(tool_calls_list) == 0 and content_arguments:
            a = extract_json_from_string(content_arguments)
            if a is not None:
                try:
                    content_arguments_json = json.loads(a)
                    tool_calls_list.append({'id': str(uuid.uuid4().hex), 'name': content_arguments_json['name'], 'arguments': json.dumps(content_arguments_json['arguments'], ensure_ascii=False)})
                except Exception as e:
                    bHasError = True
                    response_message.append(a)
            else:
                bHasError = True
                response_message.append(content_arguments)
            if bHasError:
                self.logger.bind(tag=TAG).error(f'function call error: {content_arguments}')
        if not bHasError and len(tool_calls_list) > 0:
            direct_answer_calls = [tc for tc in tool_calls_list if tc['name'] == 'direct_answer']
            real_tool_calls = [tc for tc in tool_calls_list if tc['name'] != 'direct_answer']
            if direct_answer_calls:
                self.logger.bind(tag=TAG).debug(f'模型选择 direct_answer，流式已播报，写入对话历史')
                for tc in direct_answer_calls:
                    da_response = self._extract_direct_answer_response(tc.get('arguments', '{}'))
                    if da_response:
                        sent_len = tc.get('_da_sent', 0)
                        remaining = da_response[sent_len:]
                        if remaining:
                            remaining = self._clean_response_garbage(remaining)
                            if remaining:
                                self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.MIDDLE, content_type=ContentType.TEXT, content_detail=remaining))
                        da_response = self._clean_response_garbage(da_response)
                        self.tts.store_tts_text(current_sentence_id, da_response)
                        self.dialogue.put(Message(role='assistant', content=da_response))
                if not real_tool_calls:
                    if depth == 0:
                        self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION))
                    return
                tool_calls_list = real_tool_calls
        if not bHasError and len(tool_calls_list) > 0:
            self.logger.bind(tag=TAG).debug(f'检测到 {len(tool_calls_list)} 个工具调用')
            streamed_text = ''
            if len(response_message) > 0:
                streamed_text = ''.join(response_message)
                self.tts.store_tts_text(current_sentence_id, streamed_text)
                self.dialogue.put(Message(role='assistant', content=streamed_text))
            response_message.clear()
            futures_with_data = []
            for tool_call_data in tool_calls_list:
                self.logger.bind(tag=TAG).debug(f"function_name={tool_call_data['name']}, function_id={tool_call_data['id']}, function_arguments={tool_call_data['arguments']}")
                tool_input = json.loads(tool_call_data.get('arguments') or '{}')
                enqueue_tool_report(self, tool_call_data['name'], tool_input)
                future = asyncio.run_coroutine_threadsafe(self.func_handler.handle_llm_function_call(self, tool_call_data), self.loop)
                futures_with_data.append((future, tool_call_data, tool_input))
            tool_call_timeout = int(self.config.get('tool_call_timeout', 30))
            tool_results = []
            for future, tool_call_data, tool_input in futures_with_data:
                try:
                    result = future.result(timeout=tool_call_timeout)
                    tool_results.append((result, tool_call_data))
                    enqueue_tool_report(self, tool_call_data['name'], tool_input, str(result.result) if result.result else None, report_tool_call=False)
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"工具调用超时或异常: {tool_call_data['name']}, 错误: {e}")
                    tool_results.append((ActionResponse(action=Action.ERROR, result='哎呀，网络遇到点问题，请稍后再试下！'), tool_call_data))
                    enqueue_tool_report(self, tool_call_data['name'], tool_input, str(e), report_tool_call=False)
            if tool_results:
                self._handle_function_result(tool_results, depth=depth, streamed_text=streamed_text)
    if len(response_message) > 0:
        text_buff = ''.join(response_message)
        self.tts.store_tts_text(current_sentence_id, text_buff)
        self.dialogue.put(Message(role='assistant', content=text_buff))
    if depth == 0:
        self.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=current_sentence_id, sentence_type=SentenceType.LAST, content_type=ContentType.ACTION))
        self.logger.bind(tag=TAG).debug(lambda: json.dumps(self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False))
    return True
