"""真实固定上游控制流＋CPU替身；取消必须join线程并清空全部请求状态。"""
import importlib.util
from pathlib import Path
from types import MethodType, SimpleNamespace as NS
from contextlib import nullcontext
import threading
import time
import uuid
import os
import subprocess
import json

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('tested_stream_runtime', ROOT/'scripts/development/cosyvoice/stream_runtime.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)


class Tensor:
    def __init__(self, values=None, shape=None):
        self.shape = shape or (len(values),)
    def unsqueeze(self, dim): return Tensor(shape=(1, self.shape[0]))
    def cpu(self): return self


def model_case(*, fail=False):
    fake_torch = NS(zeros=lambda *shape, **kw: Tensor(shape=shape), int32='int32',
                    tensor=lambda values: Tensor(values), cuda=NS(is_available=lambda:False))
    namespace = {'__name__':'fixed_fixture','torch':fake_torch,'uuid':uuid,'threading':threading,
                 'time':time,'np':np}
    fixture = ROOT/'tests/fixtures/cosyvoice_tts_074ca6d.py'
    exec(compile(fixture.read_text(encoding='utf-8'),str(fixture),'exec'),namespace)
    guard = runtime.StreamRuntime(); stopped=threading.Event(); workers=[]
    class Model:
        def __init__(self):
            self.lock=threading.Lock();self.tts_speech_token_dict={};self.llm_end_dict={};self.hift_cache_dict={}
            self.token_hop_len=25;self.token_max_hop_len=100;self.stream_scale_factor=2
            self.flow=NS(pre_lookahead_len=3);self.calls=0
        def llm_job(self,*args):
            key=args[-1];workers.append(threading.current_thread())
            try:
                for i in range(200):
                    if guard.cancelled(guard.state(key)): break
                    if fail:
                        guard.state(key)['error']='SyntheticProducerError';break
                    self.tts_speech_token_dict[key].append(i);time.sleep(.001)
            finally:self.llm_end_dict[key]=True;stopped.set()
        def token2wav(self,**kwargs):self.calls+=1;return Tensor(shape=(1,100))
    model=Model();model.tts=MethodType(runtime._adapt_tts(namespace['tts'],guard),model)
    return model,guard,stopped,workers


def assert_clean(model,guard,stopped,workers):
    assert stopped.wait(1)
    assert all(not thread.is_alive() for thread in workers)
    assert not model.tts_speech_token_dict and not model.llm_end_dict and not model.hift_cache_dict
    assert guard.snapshot()['active_requests']==0


def test_close_at_first_audio_cancels_producer_and_runs_original_cleanup():
    model,guard,stopped,workers=model_case()
    iterator=model.tts(stream=True)
    assert next(iterator)['tts_speech'] is not None
    assert not stopped.is_set()  # 不是预先耗尽模型再假称流式。
    iterator.close()
    assert_clean(model,guard,stopped,workers)


def test_frontend_for_yield_close_also_reaches_inner_generator_cleanup():
    model,guard,stopped,workers=model_case()
    def frontend():
        for output in model.tts(stream=True):yield output
    iterator=frontend();next(iterator);iterator.close()
    assert_clean(model,guard,stopped,workers)


def test_normal_exhaustion_and_following_round_have_no_shared_state():
    model,guard,stopped,workers=model_case()
    assert list(model.tts(stream=True))
    assert_clean(model,guard,stopped,workers)
    model.token_hop_len=25
    assert list(model.tts(stream=False))
    assert_clean(model,guard,stopped,workers)


def test_producer_failure_does_not_leave_poll_loop_or_owner_state():
    model,guard,stopped,workers=model_case(fail=True)
    with pytest.raises(RuntimeError,match='token_producer_failed'):
        list(model.tts(stream=True))
    assert_clean(model,guard,stopped,workers)


def test_cancel_before_first_audio_suppresses_generation_and_cleans_state():
    model,guard,stopped,workers=model_case()
    guard.external_cancel=threading.Event();guard.external_cancel.set()
    with pytest.raises(runtime.StreamCancelled):list(model.tts(stream=True))
    assert model.calls==0
    assert_clean(model,guard,stopped,workers)


def test_unknown_model_fails_closed_without_modifying_any_methods():
    model=NS(llm=NS(),tts=lambda:None,llm_job=lambda:None)
    before=dict(vars(model));result=runtime.install_stream_runtime(model)
    assert not result.applied and vars(model)==before


def test_installed_python310_accepts_exact_contract_without_cuda_initialization():
    main=ROOT.parents[2] if ROOT.parent.name=='worktrees' else ROOT
    source=main/'local/runtime/CosyVoice';python=source/'.venv/Scripts/python.exe'
    if not python.is_file():pytest.skip('owner-installed Cosy interpreter unavailable')
    driver='''import sys,json,threading
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from cosyvoice.cli.model import CosyVoice3Model
from stream_runtime import install_stream_runtime
class LLM:
 advances=0
 closed=0
 def inference(self,*a,**kw):
  try:
   self.advances+=1;yield 1
   self.advances+=1;yield 2
  finally:self.closed+=1
 def inference_bistream(self,*a,**kw):yield 1
model=object.__new__(CosyVoice3Model);model.llm=LLM()
guard=install_stream_runtime(model)
import torch
assert guard.applied,guard.reason
stop=threading.Event();stop.set()
guard.local.state={'stop':stop,'external':None}
assert list(model.llm.inference())==[] and model.llm.advances==0
stop.clear();iterator=model.llm.inference();assert next(iterator)==1
stop.set();assert list(iterator)==[]
assert model.llm.advances==1 and model.llm.closed==1
assert not torch.cuda.is_initialized()
print(json.dumps({'accepted':True,'cuda_initialized':False}))
'''
    env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='';env.pop('PYTHONPATH',None)
    result=subprocess.run([str(python),'-B','-X','utf8','-c',driver,
        str(ROOT/'scripts/development/cosyvoice'),str(source)],capture_output=True,cwd=ROOT,
        env=env,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stderr.decode('utf-8',errors='replace')[-1800:]
    assert json.loads(result.stdout)=={'accepted':True,'cuda_initialized':False}
