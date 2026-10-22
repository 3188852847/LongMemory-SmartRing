"""在现装3.10/3.12运行真实数值包装及投影；不接服务、模型或真实音频。"""

import json
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/development/xiaozhi'))

import voice_input_observation as input_observer
import voice_vad_signal_observation as observer
import voice_signal_diagnostics as projection
import control_http
from device_control import DeviceControl


def main():
    original = struct.pack('<960h', *([500] * 960))
    output = struct.pack('<960h', *([250] * 960))
    failure = [None]
    calls = []
    class Connection:
        _longmemory_input_observation_installed = True
        client_is_speaking = True
        def _decode_opus_packet(self, frame):
            return frame
        def _apply_aec(self, timestamp, frame):
            calls.append(True)
            assert frame is original
            if failure[0] is not None:
                raise failure[0]
            return output
    conn = Connection()
    previous = input_observer._ObservedVAD.is_vad
    try:
        assert projection.snapshot(conn, version=2)['state'] == 'not_observed'
        assert vars(conn) == {}
        observer.install_voice_vad_signal_observation(Connection, input_observation_module=input_observer)
        assert conn._apply_aec(0, original) is output
        before = time.monotonic_ns() // 1_000_000
        value = projection.snapshot(conn, version=2)
        after = time.monotonic_ns() // 1_000_000
        assert before <= value['clock_ms'] <= after
        pairs = value['aec_pairs']['total']
        assert pairs['valid'] == 1 and pairs['ratio_bins'] == [0, 0, 0, 1, 0, 0]
        generation = value['observation_generation']
        for _ in range(3):
            assert projection.snapshot(conn, version=2)['aec_pairs'] == value['aec_pairs']
            assert projection.snapshot(conn)['version'] == 1
        assert len(calls) == 1
        error = BaseException('synthetic-original-error')
        failure[0] = error
        try:
            conn._apply_aec(0, original)
        except BaseException as caught:
            assert caught is error
        else:
            raise AssertionError('original exception was hidden')
        final = projection.snapshot(conn, version=2)
        assert final['aec_pairs']['total']['original_error'] == 1
        assert final['aec_pairs']['total']['valid'] == 1
        assert final['observation_generation'] == generation and len(calls) == 2
        conn.websocket = SimpleNamespace(state=SimpleNamespace(name='OPEN'))
        control = DeviceControl('synthetic')
        control.attach(conn, 'synthetic')
        assert control.voice_input_signal(version=2)['aec_pairs'] == final['aec_pairs']
        assert control.voice_input_signal()['version'] == 1
        conn.websocket.state.name = 'CLOSED'
        assert control.voice_input_signal(version=2)['state'] == 'no_connection'
        assert callable(control_http.create_app)
        assert projection.snapshot(None, version=2)['clock_ms'] is None
        assert 'torch' not in sys.modules and 'onnxruntime' not in sys.modules
        print(json.dumps(dict(python='.'.join(map(str, sys.version_info[:3])),
            clock_implementation=time.get_clock_info('monotonic').implementation,
            clock_resolution_seconds=time.get_clock_info('monotonic').resolution,
            clock_inside_local_bounds=True, original_exception_identity_preserved=True,
            original_calls=2, getter_added_calls=0, pair_total=final['aec_pairs']['total'],
            v1_default_preserved=True, v2_bytes=len(json.dumps(final).encode()),
            actual_device_control_and_http_module_imported=True,
            no_connection_clock_is_null=True, network_used=False, models_loaded=False,
            torch_imported=False, audio_files_written=False)))
    finally:
        input_observer._ObservedVAD.is_vad = previous


if __name__ == '__main__':
    main()
