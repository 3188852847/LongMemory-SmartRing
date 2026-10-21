"""设备状态的合法上界合成样本；不读取连接、设备或个人记录。"""

from longmemory.adapters.device_control import protocol
from longmemory.adapters.device_control.voice_input_observation import (
    COUNTERS as INPUT_COUNTERS, FIELDS, FLAGS, KINDS, LIMIT, VALUE_KIND,
)
from longmemory.adapters.device_control.voice_interruption import COUNTERS as OUTPUT_COUNTERS
from longmemory.adapters.device_control.tts_interrupt import COUNTERS as WIRE_COUNTERS


def maximum_existing_status():
    precise = 9007199254740991
    flags = {name: False for name in FLAGS}
    flags['listen_mode'] = 'realtime'
    phase = dict.fromkeys(FIELDS, LIMIT)
    phase.update(version=1, state='observed', value_kind=VALUE_KIND,
                 counts=dict.fromkeys(INPUT_COUNTERS, LIMIT), inflight=dict.fromkeys(KINDS, LIMIT),
                 current_flags=flags, last_handle_flags=dict(flags), counter_saturated=True)
    output = dict(version=1, enabled=True, connection_present=True, installed=True,
                  status='observed', epoch=precise, active_output=True, active_tts_calls=precise,
                  closed=True, configuration=dict(delivery_mode='buffered', value_kind='configuration'),
                  observed=dict(value_kind='observed_client_branch', producer_path='complete_wav_fallback',
                                request_delivery_mode='full_wav', v2_transport_confirmed=False,
                                server_model_delivery_mode='unconfirmed', server_reply_cache_hit='unconfirmed'),
                  counts=dict.fromkeys(OUTPUT_COUNTERS, precise),
                  last_stage=dict(event='first_segment_callback_returned', at_ms=precise, epoch=precise),
                  device_playback_acknowledged=False)
    latency = dict(version=6, state='failed', started_at='9999-12-31T23:59:59.999999+23:59',
                   tts_backend='cosyvoice3', response_path='preset',
                   timings_ms=dict.fromkeys(protocol.VOICE_TIMING_FIELDS, 3600000),
                   input_timings_ms=dict.fromkeys(protocol.VOICE_INPUT_TIMING_FIELDS, 30000),
                   failure=dict(stage='model', code='model_connection_failed', at_ms=3600000),
                   tts_segments=[dict(index=i, started_ms=1000000, completed_ms=3600000,
                                      duration_ms=2600000, opus_packets=1000000,
                                      audio_duration_ms=60000000) for i in range(1, 65)])
    prefetch = dict(version=1, enabled=True, latest_status='speech_resumed')
    prefetch.update(dict.fromkeys(('started', 'reused', 'invalidated', 'skipped_busy', 'failed', 'fallback'), 1000000))
    prefetch.update(dict.fromkeys(('latest_prefetch_ms', 'latest_formal_wait_ms', 'latest_model_queue_ms', 'latest_overlap_ms'), 3600000))
    return dict(connection_count=1, ready=True, read_volume_supported=True, set_volume_supported=True,
                read_status_supported=True, set_brightness_supported=True, set_theme_supported=True,
                aec_advertised=True, announcement_supported=True, announcement_ready=True,
                stop_speech_supported=True, user_session_active=True,
                allowed_volume=dict(minimum=5, maximum=100), voice_mode='pipeline', voice_latency_mode='realtime',
                natural_interruption=dict(version=1, state='trial_ready', device_aec_advertised=True,
                    server_aec_active=True, timestamped_audio_supported=True, listen_mode='realtime',
                    reason='ready_for_controlled_trial'), voice_input_observation=phase,
                voice_interruption=output, voice_latency=latency, voice_asr_prefetch=prefetch,
                tts_interrupt=dict(version=1, state='closed', negotiated=True, reason='cancelled_write_unsettled',
                    counts=dict.fromkeys(WIRE_COUNTERS, precise), active_writes=precise,
                    device_playback_acknowledged=False),
                voice_prediction_shadow=dict(version=1, state='observing', opportunities=1000000,
                    evaluated=1000000, hits=500000, misses=500000, last_result='hit_affirmative'),
                voice_feedback=dict(version=1, kind='model', status='query_failed', cue_state='unavailable',
                    query_ms=3600000, first_feedback_ms=3600000, first_answer_ms=3600000),
                reason='device_timeout_outcome_unknown', announcement_reason='device_timeout_outcome_unknown')
