import asyncio
from io import BytesIO
import math
import struct
import wave

from longmemory.application.voice_benchmark import (
    CASES,
    case_by_id,
    inspect_wave,
    measure_buffered_speech,
)


def pcm_wave(seconds=0.1, rate=16000, amplitude=4000):
    samples = [int(math.sin(index / 8) * amplitude) for index in range(int(seconds * rate))]
    output = BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(rate)
        target.writeframes(b''.join(struct.pack('<h', value) for value in samples))
    return output.getvalue()


def test_cases_are_synthetic_stable_and_address_different_failures():
    assert [item.id for item in CASES] == [
        'short_reply', 'numbers_time', 'mixed_language', 'expressive',
    ]
    assert case_by_id('numbers_time') is CASES[1]
    assert case_by_id('missing') is None
    assert len({item.purpose for item in CASES}) == len(CASES)


def test_wave_inspection_reports_duration_and_near_silence():
    voiced = inspect_wave(pcm_wave(), 'audio/wav')
    silent = inspect_wave(pcm_wave(amplitude=0), 'audio/wav')
    assert voiced is not None
    assert voiced['duration_seconds'] == 0.1
    assert voiced['sample_rate_hz'] == 16000 and voiced['near_silent'] is False
    assert silent is not None and silent['near_silent'] is True
    assert inspect_wave(b'ID3-synthetic', 'audio/mpeg') is None


def test_buffered_measurement_is_honest_about_first_available_audio():
    class Backend:
        async def speech(self, text):
            assert text == CASES[0].text
            return pcm_wave(), 'audio/wav'

    result = asyncio.run(measure_buffered_speech(Backend(), CASES[0]))
    assert result['adapter_delivery'] == 'buffered'
    assert result['first_audio_available_ms'] == result['completed_ms']
    assert result['audio_bytes'] > 44 and result['wave']['near_silent'] is False
