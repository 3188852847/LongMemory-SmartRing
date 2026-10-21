"""真实producer摘要的严格有限投影，不连接设备或服务。"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from longmemory.adapters.device_control.protocol import BridgeError
from longmemory.adapters.device_control.tts_interrupt import COUNTERS, tts_interrupt


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]/'scripts/development/xiaozhi'))
    import voice_output_protocol
    return voice_output_protocol


def sample(wire):
    conn=NS()
    protocol=wire.OutputProtocol(conn,NS())
    setattr(conn,wire.ATTRIBUTE,protocol)
    protocol.hello_sent=protocol.negotiated=True
    protocol.reason='confirmed';protocol.counts['hello_confirmed']=1
    return conn,protocol


def test_actual_producer_all_states_and_closed_negotiation_are_facts(wire):
    assert COUNTERS==frozenset(wire.COUNTERS)
    values=[wire.protocol_snapshot(None),wire.protocol_snapshot(NS())]
    conn,p=sample(wire)
    values.append(p.snapshot())
    p._invalidate('connection_closed')
    values.append(p.snapshot())
    assert values[-1]['negotiated'] is True and values[-1]['state']=='closed'
    p=wire.OutputProtocol(NS(),NS());values.append(p.snapshot())
    p.hello_sent=True;p.reason='legacy_not_confirmed';values.append(p.snapshot())
    for value in values:
        output=tts_interrupt(value)
        assert output==value and output['device_playback_acknowledged'] is False
        output['counts']['start_sent']=99
        assert value['counts']['start_sent']==0


@pytest.mark.parametrize('field,bad',[
    ('version',True),('version',2),('state',[]),('state','ready'),('reason',{}),('reason','playing'),
    ('negotiated',1),('device_playback_acknowledged',True),('active_writes',True),
    ('active_writes',-1),('active_writes',9007199254740992),('counts',{}),
    ('counts',{'private_text':'synthetic'}),('state','legacy'),('reason','send_timeout')])
def test_malformed_summary_rejected_with_stable_error(wire,field,bad):
    _,p=sample(wire);value=p.snapshot();value[field]=bad
    with pytest.raises(BridgeError,match='^bridge_invalid_response$') as error:
        tts_interrupt(value)
    assert error.value.status==502


def test_extra_fields_boolean_counter_and_disconnected_history_rejected(wire):
    _,p=sample(wire)
    values=[]
    value=p.snapshot();value['private_audio']='synthetic';values.append(value)
    value=p.snapshot();value['counts']['audio_sent']=True;values.append(value)
    value=wire.protocol_snapshot(None);value['counts']['interrupt_sent']=1;values.append(value)
    value=wire.protocol_snapshot(None);value['active_writes']=1;values.append(value)
    for value in values:
        before=deepcopy(value)
        with pytest.raises(BridgeError):tts_interrupt(value)
        assert value==before
