"""AD客户端交付摘要的共同有限投影；Python 3.10/3.12均只用标准库。"""

import json

MODES = frozenset({"buffered", "incremental", "adaptive"})
FAILURES = frozenset({"before_handoff", "after_handoff", "reader_cleanup_timeout",
                      "reader_cleanup_unconfirmed", "configuration_changed"})
OUTCOMES = frozenset({"completed", "cancelled", "failed", "fallback", "preset", "blocked"})
FIELDS = frozenset({"version", "state", "requested_mode", "effective_mode", "failure_code",
                    "last_outcome", "handoff_started", "reader_cleanup", "segment_active",
                    "next_segment_allowed", "restart_required", "outcomes", "physical_playback_verified"})


def project_observation(value):
    """只接AD固定客户端摘要；坏旁路为null，不阻断其他启动状态。"""
    try:
        if (type(value) is not dict or set(value) != FIELDS
                or type(value['version']) is not int or value['version'] != 1
                or value['state'] not in ('no_connection', 'not_observed', 'configured',
                    'buffered_fallback', 'restart_required', 'invalid_configuration')
                or value['physical_playback_verified'] is not False):
            return None
        for key in ('requested_mode', 'effective_mode'):
            if value[key] is not None and (type(value[key]) is not str or value[key] not in MODES):
                return None
        if (value['failure_code'] is not None and value['failure_code'] not in FAILURES
                or value['last_outcome'] is not None and value['last_outcome'] not in OUTCOMES
                or value['reader_cleanup'] not in ('not_observed', 'not_required', 'confirmed', 'unconfirmed')
                or any(type(value[key]) is not bool for key in ('handoff_started', 'segment_active',
                    'next_segment_allowed', 'restart_required'))
                or type(value['outcomes']) is not dict or set(value['outcomes']) != OUTCOMES
                or any(type(n) is not int or not 0 <= n <= 1000000 for n in value['outcomes'].values())):
            return None
        expected_append = value['requested_mode'] is not None and not value['restart_required'] and not value['segment_active'] and value['reader_cleanup'] != 'unconfirmed'
        if value['next_segment_allowed'] != expected_append:
            return None
        if value['state'] in ('no_connection', 'not_observed', 'invalid_configuration'):
            if (value['failure_code'] is not None or value['last_outcome'] is not None
                    or value['handoff_started'] or value['segment_active']
                    or value['reader_cleanup'] != 'not_observed' or any(value['outcomes'].values())):
                return None
        if value['state'] in ('no_connection', 'invalid_configuration'):
            if (value['requested_mode'] is not None or value['effective_mode'] is not None
                    or value['restart_required'] != (value['state'] == 'invalid_configuration')):
                return None
        elif value['requested_mode'] is None:
            return None
        if value['state'] == 'restart_required':
            if not value['restart_required'] or value['effective_mode'] is not None or value['failure_code'] is None:
                return None
        elif value['state'] in ('not_observed', 'configured', 'buffered_fallback'):
            expected = 'buffered' if value['state'] == 'buffered_fallback' else value['requested_mode']
            if value['effective_mode'] != expected or value['restart_required']:
                return None
            if value['state'] == 'buffered_fallback' and (value['requested_mode'] == 'buffered' or value['failure_code'] is None):
                return None
        if value['reader_cleanup'] == 'unconfirmed' and not value['segment_active'] and value['effective_mode'] is not None:
            return None
        if len(json.dumps(value, allow_nan=False).encode('utf-8')) > 512:
            return None
        return {**value, 'outcomes': dict(value['outcomes'])}
    except Exception:
        return None
