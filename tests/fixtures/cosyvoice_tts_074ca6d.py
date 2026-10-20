# Copyright (c) 2024 Alibaba Inc (authors: Xiang Lyu)
#               2025 Alibaba Inc (authors: Xiang Lyu, Bofan Zhou)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# Fixed test-only CosyVoice2Model.tts from QwenAudio/CosyVoice 074ca6d.
# Executed with CPU doubles, never imports the model or CUDA.
def tts(self, text=torch.zeros(1, 0, dtype=torch.int32), flow_embedding=torch.zeros(0, 192), llm_embedding=torch.zeros(0, 192), prompt_text=torch.zeros(1, 0, dtype=torch.int32), llm_prompt_speech_token=torch.zeros(1, 0, dtype=torch.int32), flow_prompt_speech_token=torch.zeros(1, 0, dtype=torch.int32), prompt_speech_feat=torch.zeros(1, 0, 80), source_speech_token=torch.zeros(1, 0, dtype=torch.int32), stream=False, speed=1.0, **kwargs):
    this_uuid = str(uuid.uuid1())
    with self.lock:
        self.tts_speech_token_dict[this_uuid], self.llm_end_dict[this_uuid] = ([], False)
        self.hift_cache_dict[this_uuid] = None
    if source_speech_token.shape[1] == 0:
        p = threading.Thread(target=self.llm_job, args=(text, prompt_text, llm_prompt_speech_token, llm_embedding, this_uuid))
    else:
        p = threading.Thread(target=self.vc_job, args=(source_speech_token, this_uuid))
    p.start()
    if stream is True:
        token_offset = 0
        prompt_token_pad = int(np.ceil(flow_prompt_speech_token.shape[1] / self.token_hop_len) * self.token_hop_len - flow_prompt_speech_token.shape[1])
        while True:
            time.sleep(0.1)
            this_token_hop_len = self.token_hop_len + prompt_token_pad if token_offset == 0 else self.token_hop_len
            if len(self.tts_speech_token_dict[this_uuid]) - token_offset >= this_token_hop_len + self.flow.pre_lookahead_len:
                this_tts_speech_token = torch.tensor(self.tts_speech_token_dict[this_uuid][:token_offset + this_token_hop_len + self.flow.pre_lookahead_len]).unsqueeze(dim=0)
                this_tts_speech = self.token2wav(token=this_tts_speech_token, prompt_token=flow_prompt_speech_token, prompt_feat=prompt_speech_feat, embedding=flow_embedding, token_offset=token_offset, uuid=this_uuid, stream=stream, finalize=False)
                token_offset += this_token_hop_len
                self.token_hop_len = min(self.token_max_hop_len, self.token_hop_len * self.stream_scale_factor)
                yield {'tts_speech': this_tts_speech.cpu()}
            if self.llm_end_dict[this_uuid] is True and len(self.tts_speech_token_dict[this_uuid]) - token_offset < this_token_hop_len + self.flow.pre_lookahead_len:
                break
        p.join()
        this_tts_speech_token = torch.tensor(self.tts_speech_token_dict[this_uuid]).unsqueeze(dim=0)
        this_tts_speech = self.token2wav(token=this_tts_speech_token, prompt_token=flow_prompt_speech_token, prompt_feat=prompt_speech_feat, embedding=flow_embedding, token_offset=token_offset, uuid=this_uuid, finalize=True)
        yield {'tts_speech': this_tts_speech.cpu()}
    else:
        p.join()
        this_tts_speech_token = torch.tensor(self.tts_speech_token_dict[this_uuid]).unsqueeze(dim=0)
        this_tts_speech = self.token2wav(token=this_tts_speech_token, prompt_token=flow_prompt_speech_token, prompt_feat=prompt_speech_feat, embedding=flow_embedding, token_offset=0, uuid=this_uuid, finalize=True, speed=speed)
        yield {'tts_speech': this_tts_speech.cpu()}
    with self.lock:
        self.tts_speech_token_dict.pop(this_uuid)
        self.llm_end_dict.pop(this_uuid)
        self.hift_cache_dict.pop(this_uuid)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.current_stream().synchronize()
