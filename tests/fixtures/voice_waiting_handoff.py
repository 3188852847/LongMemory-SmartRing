"""固定上游调度器＋注入时钟的同条件交接对照；无真实模型/TTS/网络/音频。"""

import ast
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import ModuleType,SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[2]
MAIN=ROOT.parents[2] if ROOT.parent.name=='worktrees' else ROOT
UPSTREAM=MAIN/'local/runtime/xiaozhi-esp32-server'
UPSTREAM_SHA='eb4b28c59ed7ed885258498cf757ce14352d620e'
BASELINE_SHA='84048dc237c0a9609c100422e50e0474634dc651'
sys.path.insert(0,str(ROOT/'scripts/development/xiaozhi'))


def run_case(*,after,frames=35,answer_ready_ms=120):
    import voice_waiting as current
    now=[0.0];sent=[];callback=[];holder={}
    async def sleep(delay):
        now[0]+=delay
        if now[0]*1000>=answer_ready_ms:holder['state'].answer_ready=True
    clock=NS(monotonic=lambda:now[0],perf_counter=lambda:now[0],time=lambda:now[0])
    quiet=NS(bind=lambda **kw:NS(debug=lambda *a:None,error=lambda *a:None))
    scheduler_source=subprocess.check_output(['git','-C',str(UPSTREAM),'show',
        UPSTREAM_SHA+':main/xiaozhi-server/core/utils/audioRateController.py'],text=True,encoding='utf-8')
    tree=ast.parse(scheduler_source)
    tree.body=[node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='AudioRateController']
    namespace={'time':clock,'asyncio':NS(Event=asyncio.Event,sleep=sleep,CancelledError=asyncio.CancelledError),
        'deque':__import__('collections').deque,'logger':quiet,'TAG':'synthetic'}
    exec(compile(tree,'pinned_upstream_audio_scheduler','exec'),namespace)
    module=ModuleType('synthetic_sender')
    async def send(conn,packet,flow):
        sent.append((round(now[0]*1000),bytes(packet)))
        confirm=getattr(adapter,'record_packet_sent',None)
        if callable(confirm):confirm(packet)
        flow['packet_count']+=1
    def start(conn,controller,flow):
        async def deliver(packet):await module._do_send_audio(conn,packet,flow)
        controller.start_sending(deliver)
    module._do_send_audio=send;module._start_background_sender=start
    if after:
        adapter=current
    else:
        source=subprocess.check_output(['git','show',BASELINE_SHA+':scripts/development/xiaozhi/voice_waiting.py'],
            cwd=ROOT,text=True,encoding='utf-8')
        adapter=ModuleType('baseline_waiting');adapter.__file__=str(ROOT/'scripts/development/xiaozhi/voice_waiting.py')
        exec(compile(source,'pinned_baseline_waiting','exec'),adapter.__dict__)
    old_clock=adapter.time;adapter.time=clock
    try:
        conn=NS(sentence_id='synthetic',client_abort=False,stop_event=threading.Event(),
            _longmemory_voice_latency=NS(mark=lambda *a,**kw:None))
        # 本夹具只测已排队尾包的调度交接，显式跳过产品静默阈值。
        state=adapter.WaitingTurn(conn,'model',delay=0,packets=(b'cue',))
        holder['state']=state;conn._longmemory_waiting=state
        adapter.install_waiting_sender(module)
        controller=namespace['AudioRateController'](60)
        controller.start_sending=lambda deliver:callback.append(deliver)
        flow={'sentence_id':conn.sentence_id,'packet_count':0}
        module._start_background_sender(conn,controller,flow)
        for _ in range(frames):controller.add_audio(adapter.WaitingPacket(b'cue',state))
        controller.add_audio(adapter.AnswerPacket(b'answer',state))
        if answer_ready_ms==0:state.answer_ready=True
        asyncio.run(controller.check_queue(callback[0]))
        answer=next(time for time,payload in sent if payload==b'answer')
        return {'mode':'after' if after else 'before','clock':'synthetic_injected',
            'cue_frames':frames,'answer_ready_ms':answer_ready_ms,'first_answer_sent_ms':answer,
            'cue_frames_sent':sum(payload==b'cue' for _,payload in sent),
            'final_play_position_ms':controller.play_position,'real_audio_playback_verified':False}
    finally:adapter.time=old_clock


def comparison():
    rows=[run_case(after=after,frames=frames,answer_ready_ms=ready)
        for frames,ready in ((8,120),(20,120),(35,120),(35,125),(35,0)) for after in (False,True)]
    return {'baseline_sha':BASELINE_SHA,'upstream_sha':UPSTREAM_SHA,
        'scope':'already_queued_waiting_tail_only_not_end_to_end_latency', 'rows':rows}


if __name__=='__main__':
    report=comparison()
    if len(sys.argv)>1:
        with Path(sys.argv[1]).open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False))
