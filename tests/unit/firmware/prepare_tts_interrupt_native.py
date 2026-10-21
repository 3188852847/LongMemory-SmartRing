"""Extract the real 0016 consumer into an explicit, offline MSVC race fixture.

Run manually with --source/--idf/--output. No pytest collection, downloads or device I/O.
Hardware Opus/codec and FreeRTOS are stubs; identities, queue transitions, activity
counts, output barriers and application control/UI methods come from source verbatim.
Named scheduling hooks are inserted only into the generated test translation unit.
"""
import argparse
import hashlib
import json
from pathlib import Path


def between(text, start, end):
    return text[text.index(start):text.index(end, text.index(start))]


def prepare(source: Path, idf: Path, output: Path):
    if output.exists():
        raise ValueError('refusing to overwrite fixture evidence')
    audio = (source / 'main/audio/audio_service.cc').read_text(encoding='utf-8')
    app = (source / 'main/application.cc').read_text(encoding='utf-8')
    protocol = (source / 'main/protocols/protocol.h').read_text(encoding='utf-8')
    ah = (source / 'main/audio/audio_service.h').read_text(encoding='utf-8')
    output.mkdir(parents=True)
    parts = {
        'identity': between(protocol, 'struct AudioOutputIdentity', 'struct BinaryProtocol2'),
        'audio_types': between(ah, 'struct AudioServiceCallbacks', 'class AudioService'),
        'audio_state': between(ah, '    struct ManagedOutput', '    AudioCodec* codec_'),
        'channel_state': between(protocol, '    std::function<void(uint64_t)> on_local_opening_', '    std::function<void(const cJSON* root)> on_incoming_json_'),
        'queue_push': between(audio, 'bool AudioService::PushPacketToDecodeQueue', 'std::unique_ptr<AudioStreamPacket> AudioService::PopPacketFromSendQueue'),
        'audio_output': between(audio, 'void AudioService::AudioOutputTask()', 'void AudioService::OpusCodecTask()'),
        'decode': between(audio, '        /* Decode the audio from decode queue */', '        /* Encode the audio to send queue */'),
        'managed': between(audio, 'void AudioService::ResetDecoder()', 'void AudioService::CheckAndUpdateAudioPowerState()'),
        'application': between(app, '// 接收路径先同步提交音频门', 'void Application::HandleProtocolJson('),
        'state_changed': between(app, 'void Application::HandleStateChangedEvent()', 'void Application::Schedule('),
        'abort': between(app, 'void Application::AbortSpeaking(', 'void Application::SetListeningMode('),
        'receive': between(app, '    protocol_->OnIncomingAudio([this]', '    protocol_->OnLocalChannelOpening('),
    }
    original_hashes = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in parts.items()}
    parts['audio_output'] = parts['audio_output'].replace('        bool played = false;', '        hook("output_dequeued");\n        bool played = false;', 1)
    parts['decode'] = parts['decode'].replace('            lock.lock();', '            hook("decode_requeue");\n            lock.lock();', 1)
    parts['decode'] = parts['decode'].replace('                ++output->active_decode;', '                hook("decode_handoff");\n                ++output->active_decode;', 1)
    parts['decode'] = 'void AudioService::DecodeOne() {\n std::unique_lock<std::mutex> lock(audio_queue_mutex_);\n do {\n' + parts['decode'] + '\n } while (false);\n}\n'
    receive = parts['receive']
    parts['receive'] = 'void Application::Receive(std::unique_ptr<AudioStreamPacket> packet) {\n' + receive[receive.index('        std::lock_guard'):receive.rindex('    });')] + '\n}\n'
    template = Path(__file__).with_name('tts_interrupt_native.cpp.in').read_text(encoding='utf-8')
    for key, value in parts.items():
        template = template.replace('@' + key + '@', value)
    (output / 'consumer.cpp').write_text(template, encoding='utf-8')
    cjson = idf / 'components/json/cJSON'
    if not (cjson / 'cJSON.c').is_file():
        raise ValueError('missing installed SDK cJSON')
    (output / 'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(tts_interrupt_native LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
add_executable(consumer consumer.cpp "{cjson.as_posix()}/cJSON.c")
target_include_directories(consumer PRIVATE "{cjson.as_posix()}")
target_compile_options(consumer PRIVATE /utf-8)
add_executable(legacy_client consumer.cpp "{cjson.as_posix()}/cJSON.c")
target_include_directories(legacy_client PRIVATE "{cjson.as_posix()}")
target_compile_definitions(legacy_client PRIVATE CONFIG_BOARD_TYPE_VIEWE_SMARTRING_PLUS=0)
target_compile_options(legacy_client PRIVATE /utf-8)
''', encoding='utf-8')
    hashes = {str(p.relative_to(source)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [source / 'main/audio/audio_service.cc', source / 'main/audio/audio_service.h', source / 'main/application.cc', source / 'main/protocols/protocol.h']}
    (output / 'source-binding.json').write_text(json.dumps({'source': str(source), 'hashes': hashes, 'extracted_sections': original_hashes, 'test_hooks': ['decode_handoff', 'decode_requeue', 'output_dequeued']}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--idf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.idf, args.output)
