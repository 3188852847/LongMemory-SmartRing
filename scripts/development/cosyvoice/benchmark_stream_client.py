"""隔离基准的Python3.10真实重采样/Opus消费端；无模型、麦克风或设备。"""
import http.client
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import types
import uuid
import wave


def run(config):
    root=Path(config['source_root']);voice=Path(config['voice_root'])
    sys.path[:0]=[str(root/'scripts/development/xiaozhi'),str(voice)]
    opus=voice/'native/libopus-1.6.1/Library/bin'
    os.environ['PATH']=str(opus)+os.pathsep+os.environ.get('PATH','')
    dll=os.add_dll_directory(str(opus))
    from core.utils.opus_encoder_utils import OpusEncoderUtils
    from opuslib_next import Decoder
    # 基准只借用现有编码器。无需初始化上游ASR/日志或真实连接对象。
    dto=types.ModuleType('core.providers.tts.dto.dto');dto.SentenceType=types.SimpleNamespace(FIRST='first')
    cleaner=types.ModuleType('core.utils.tts');cleaner.MarkdownCleaner=types.SimpleNamespace(clean_markdown=lambda x:x)
    util=types.ModuleType('core.utils.util');util.audio_bytes_to_data_stream=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('preset_forbidden'))
    for name,module in ((dto.__name__,dto),(cleaner.__name__,cleaner),(util.__name__,util)):sys.modules[name]=module
    import cosyvoice_streaming as consumer
    consumer.STREAM_URL=config['url'];consumer.default_voice_active=lambda:False;consumer.for_sentence=lambda *a:None
    quiet=types.SimpleNamespace(bind=lambda **kw:types.SimpleNamespace(warning=lambda *a:None))
    connection=types.SimpleNamespace(sample_rate=config.get('sample_rate',24000),sentence_id=None,client_abort=False,
        _longmemory_cosy_delivery_mode=config['mode'],_longmemory_cosy_reply_cache=config.get('cache',False),logger=quiet)
    encoder=OpusEncoderUtils(connection.sample_rate,1,60)
    def fallback(*args,**kwargs):raise AssertionError('unexpected_full_wav_fallback')
    tts=types.SimpleNamespace(to_tts_stream=fallback,current_sentence_id=None,tts_stop_request=False,
        tts_timeout=40,_correct_words_pattern=None,opus_encoder=encoder,tts_audio_queue=types.SimpleNamespace(put=lambda x:None))
    connection.tts=tts;consumer.install_cosyvoice_streaming(tts,connection)
    if config.get('segmented'):
        # 文字已完整可用，只测现行自然分段后的TTS供给；不伪造LLM首字等待。
        from cosyvoice_segments import install_cosyvoice_punctuation_policy
        tts._get_segment_text=lambda:None
        tts._process_remaining_text_stream=lambda **kw:None
        tts.conn=connection
        install_cosyvoice_punctuation_policy(tts)
        original_stream=tts.to_tts_stream
        def segment_stream(text, *args, **kwargs):
            holder['row']['segments'].append({'chars':len(text),
                'at_ms':round((time.perf_counter()-holder['started'])*1000,3)})
            return original_stream(text,*args,**kwargs)
        tts.to_tts_stream=segment_stream
    original_decode=consumer._wav_chunk_to_pcm;holder={}
    def observe_decode(wav,rate):
        row=holder['row'];received=(time.perf_counter()-holder['started'])*1000
        with wave.open(io.BytesIO(wav),'rb') as source:duration=source.getnframes()*1000/source.getframerate()
        pcm=original_decode(wav,rate)
        row['chunks'].append({'at_ms':round((time.perf_counter()-holder['started'])*1000,3),
                              'received_at_ms':round(received,3),'audio_ms':duration})
        holder['pcm'].append(pcm);return pcm
    consumer._wav_chunk_to_pcm=observe_decode
    outputs=[]
    def one(text,cancel_after=None):
        connection.client_abort=False;connection.sentence_id=uuid.uuid4().hex;tts.current_sentence_id=connection.sentence_id
        row={'chunks':[],'packet_arrivals_ms':[],'segments':[],
             'segmented':bool(config.get('segmented')),
             'cancel_after_packets':cancel_after,'sample_rate':connection.sample_rate}
        holder.update(row=row,started=time.perf_counter(),pcm=[],decoded=[])
        decoder=Decoder(connection.sample_rate,1)
        def deliver(packet):
            assert connection.sentence_id==tts.current_sentence_id
            values=decoder.decode(packet,connection.sample_rate*60//1000)
            assert len(values)==connection.sample_rate*60//1000*2
            row['packet_arrivals_ms'].append(round((time.perf_counter()-holder['started'])*1000,3))
            holder['decoded'].append(values)
            if cancel_after and len(row['packet_arrivals_ms'])>=cancel_after:connection.client_abort=True
        if config.get('segmented'):
            tts.tts_text_buff=[text];tts.processed_chars=0;tts.is_first_sentence=True
            tts._process_remaining_text_stream(opus_handler=deliver)
        else:
            tts.to_tts_stream(text,opus_handler=deliver)
        row['total_ms']=round((time.perf_counter()-holder['started'])*1000,3)
        row['first_pcm_ms']=row['chunks'][0]['at_ms'] if row['chunks'] else None
        row['first_opus_ms']=row['packet_arrivals_ms'][0] if row['packet_arrivals_ms'] else None
        row['audio_ms']=sum(item['audio_ms'] for item in row['chunks'])
        row['opus_frames']=len(row['packet_arrivals_ms'])
        row['rtf']=round(row['total_ms']/row['audio_ms'],5) if row['audio_ms'] else None
        cursor=row['first_opus_ms'];gaps=[]
        if cursor is not None:
            for at in row['packet_arrivals_ms']:
                if at>cursor:gaps.append(at-cursor);cursor=at
                cursor+=60
        row['estimated_supply_gap_ms']=round(sum(gaps),3);row['estimated_max_gap_ms']=round(max(gaps,default=0),3)
        row['physical_playback_verified']=False
        if config.get('audio_output') and not cancel_after:
            target=Path(config['audio_output'])
            with wave.open(str(target),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(b''.join(holder['pcm']))
            with wave.open(str(target.with_suffix('.opus-decoded.wav')),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(connection.sample_rate)
                output.writeframes(b''.join(holder['decoded']))
        outputs.append(row)
    try:
        one(config['text'],config.get('cancel_after_packets'))
        if config.get('cancel_after_packets'):
            began=time.perf_counter();limit=began+8
            from urllib.parse import urlsplit
            port=urlsplit(config['url']).port
            while time.perf_counter()<limit:
                c=http.client.HTTPConnection('127.0.0.1',port,timeout=1);c.request('GET','/health');r=c.getresponse();health=json.loads(r.read(65536));c.close()
                if not health.get('generation_in_flight') and health.get('stream_runtime',{}).get('active_requests')==0:break
                time.sleep(.05)
            else:raise AssertionError('cancel_cleanup_timeout')
            outputs[0]['server_cleanup_wait_ms']=round((time.perf_counter()-began)*1000,3)
            one('新的一轮已经开始，我们继续聊。')
        return {'rounds':outputs,'decoder':'installed_opuslib_next','physical_playback_verified':False}
    finally:encoder.close();dll.close()


if __name__=='__main__':
    result=run(json.loads(sys.stdin.buffer.read()))
    print(json.dumps(result,ensure_ascii=False))
