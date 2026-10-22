"""纯回声判据的固定公开输入观测；不改算法、不构造部署候选。"""

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
HELPER_HASH = "5e535e8cb3e6a10d6bb977f42aba697f2884d266f3cd09ce48e137a8cf2da156"
PATH_CASES = ("echo_path_delay10ms_fir", "double_path_delay10ms_fir")


def load_helpers():
    path = Path(__file__).with_name("aec_window_ablation.py")
    blob = path.read_bytes()
    if hashlib.sha256(blob).hexdigest() != HELPER_HASH:
        raise ValueError("frozen_helper_changed")
    helper = ModuleType("frozen_ablation")
    helper.__file__ = str(path)
    exec(compile(blob,str(path),"exec"),helper.__dict__)
    return helper, helper.load_base()


def instrument(node):
    """只在限幅前读取本次局部变量，反向移除后逐节点等同原AST。"""
    result = copy.deepcopy(node)
    body = next(item for item in result.body if isinstance(item,ast.Try)).body
    positions = [i for i,item in enumerate(body) if isinstance(item,ast.Assign)
                 and isinstance(item.value,ast.Call) and isinstance(item.value.func,ast.Attribute)
                 and isinstance(item.value.func.value,ast.Name) and item.value.func.value.id == "np"
                 and item.value.func.attr == "clip"]
    if len(positions) != 1:
        raise ValueError("unexpected_aec_clip_shape")
    index = positions[0]
    body.insert(index,ast.parse("_criterion(best_ts, aligned_ref, best_corr, ref_rms, scale, coef, mic_audio)").body[0])
    stripped = copy.deepcopy(result)
    next(item for item in stripped.body if isinstance(item,ast.Try)).body.pop(index)
    if ast.dump(stripped) != ast.dump(node):
        raise ValueError("probe_changed_algorithm")
    return ast.fix_missing_locations(result)


def waveform_metrics(output, raw, near, has_near, has_echo, np):
    y,x,n = (np.frombuffer(pcm,dtype="<i2").astype(np.float64) for pcm in (output,raw,near))
    if not len(y) or y.shape != x.shape or x.shape != n.shape:
        raise ValueError("metric_shape_mismatch")
    result = dict(output_rms=float(np.sqrt(np.mean(y*y))))
    if has_near:
        error = y-n
        result.update(error_to_known_near_rms=float(np.sqrt(np.mean(error*error))),
                      error_energy_over_near_energy=float(np.dot(error,error)/np.dot(n,n)))
    if has_echo and not has_near:
        result["echo_only_residual_energy_ratio"] = float(np.dot(y,y)/np.dot(x,x))
    return result


def path_echo(far, np):
    """预先固定的10ms延迟与两抽头路径，不拟合输出，不更换增益。"""
    x = np.frombuffer(far,dtype="<i2").astype(np.float64)[:96000]
    a = np.pad(x,(160,0))[:96000]
    b = np.pad(x,(161,0))[:96000]
    return np.rint(.55*(.8*a+.2*b)).astype("<i2").tobytes()


def prepare(args,helper,base):
    run,out = args.baseline_run,args.output
    prior = json.loads(base.checked((run/"summary.json").read_bytes(),helper.BASE_SUMMARY_HASH))
    base.checked((run/"config.json").read_bytes(),helper.BASE_CONFIG_HASH)
    if prior["state"] != "complete" or len(prior["cases"]) != 5:
        raise ValueError("baseline_changed")
    for name,expected in base.SOURCE_HASHES.items():
        with (out/name).open("xb") as stream:
            stream.write(base.checked((run/"sources"/name).read_bytes(),expected))
    for name,expected in base.FIXTURES.items():
        base.checked((run/"fixtures"/name).read_bytes(),expected)
    base.checked(args.model.read_bytes(),base.MODEL_HASH)
    far = helper.read_pcm(run/"far_16k_reference.wav")
    if len(far) != (base.FRAMES+base.LEAD)*base.FRAME*2:
        raise ValueError("reference_length_changed")
    base.write_wave(out/"far_reference.wav",far)
    for row in prior["cases"]:
        raw = helper.read_pcm(run/row["case"]/"input.wav")
        base.checked(raw,row["input_pcm_sha256"])
        if len(raw) != 192000:
            raise ValueError("input_length_changed")
        folder = out/row["case"]
        folder.mkdir()
        base.write_wave(folder/"input.wav",raw)
    for name in PATH_CASES:
        (out/name).mkdir()
    for name,blob in (("baseline-summary.json",(run/"summary.json").read_bytes()),
                       ("baseline-config.json",(run/"config.json").read_bytes()),
                       ("harness.py",Path(__file__).read_bytes())):
        with (out/name).open("xb") as stream:
            stream.write(blob)
    base.write_json(out/"config.json",dict(input_scenarios=7,processing_arms=["pinned_original_with_readonly_probe"],
        every_packet_compared_to_uninstrumented_original=True,source_hashes=base.SOURCE_HASHES,
        model_sha256=base.MODEL_HASH,baseline_summary_sha256=helper.BASE_SUMMARY_HASH,
        baseline_config_sha256=helper.BASE_CONFIG_HASH,baseline_harness_sha256=helper.BASE_HARNESS_HASH,
        helper_sha256=HELPER_HASH,harness_sha256=base.digest(Path(__file__).read_bytes()),settings=base.SETTINGS,
        path_control=dict(delay_samples=160,fir=[.8,.2],gain=.55,reference_unchanged=True),
        metric_limits="mixed output-minus-near includes residual echo and near distortion; conditional difference is not source isolation"))


def worker(args,helper,base):
    for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    os.environ.update(CUDA_VISIBLE_DEVICES="-1",USE_TORCH="0",USE_TF="0",USE_FLAX="0",
                      HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
    import numpy as np
    import onnxruntime as ort
    wall,cpu = time.monotonic(),time.process_time()
    def budget():
        if time.monotonic()-wall >= args.max_seconds:
            raise TimeoutError("worker_wall_deadline")
    out,warnings,observed = args.output,[],[]
    logger = base.replay_logger(warnings)
    methods = base.source_methods((out/"connection.py").read_text(encoding="utf-8"))
    original = base.compile_node(methods["_apply_aec"],{"np":np,"logger":logger,"TAG":"criterion-offline"})
    def capture(ts,ref,corr,ref_rms,scale,coef,mic):
        a,b = mic.astype(np.float64),ref.astype(np.float64)
        a,b = a-a.mean(),b-b.mean()
        observed.append(dict(actual_reference_timestamp=int(ts),actual_reference_sha256=base.digest(ref.astype("<i2").tobytes()),
            best_corr=float(corr),ref_rms=float(ref_rms),scale=float(scale),coef=float(coef),
            extra_point_three=bool(corr >= .97 and ref_rms > 500),
            centered_time_correlation=float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-8))))
    probe_node = instrument(methods["_apply_aec"])
    probe = base.compile_node(probe_node,{"np":np,"logger":logger,"TAG":"criterion-offline","_criterion":capture})
    reset = base.compile_reset(methods["reset_audio_states"])
    tick = SimpleNamespace(milliseconds=base.BASE)
    namespace = {"np":np,"time":SimpleNamespace(time=lambda:tick.milliseconds/1000),
                 "logger":logger,"TAG":"criterion-offline","VADProviderBase":object}
    cls = next(item for item in ast.parse((out/"silero.py").read_text(encoding="utf-8")).body
               if isinstance(item,ast.ClassDef) and item.name == "VADProvider")
    base.compile_node(cls,namespace)
    opts = ort.SessionOptions()
    opts.inter_op_num_threads = opts.intra_op_num_threads = 1
    base.checked(args.model.read_bytes(),base.MODEL_HASH)
    session = ort.InferenceSession(str(args.model),providers=["CPUExecutionProvider"],sess_options=opts)
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("provider_changed")
    class Inference:
        def run(self,names,feed):
            if feed["input"].shape != (1,576) or feed["state"].shape != (2,1,128) or feed["sr"].item() != 16000:
                raise ValueError("vad_input_changed")
            return session.run(names,feed)
    def detector():
        value = namespace["VADProvider"].__new__(namespace["VADProvider"])
        value.session = Inference()
        value.vad_threshold,value.vad_threshold_low = .5,.3
        value.silence_threshold_ms,value.frame_window_threshold = 600,3
        return value,base.vad_connection(logger)
    prior = json.loads((out/"baseline-summary.json").read_text(encoding="utf-8"))
    originals = {row["case"]:row for row in prior["cases"]}
    far,near = helper.read_pcm(out/"far_reference.wav"),helper.read_pcm(out/"near_only/input.wav")
    echo = path_echo(far,np)
    double = base.pcm16(np.frombuffer(echo,dtype="<i2").astype(float)+np.frombuffer(near,dtype="<i2"),np).tobytes()
    for name,pcm in zip(PATH_CASES,(echo,double)):
        base.write_wave(out/name/"input.wav",pcm)
    configurations = list(base.CASES)+[(PATH_CASES[0],False,True,True,0),(PATH_CASES[1],True,True,True,0)]
    results,all_pcm = [],{}
    for name,has_near,has_echo,cache_enabled,offset in configurations:
        budget()
        folder,cache = out/name,{}
        raw = helper.read_pcm(folder/"input.wav")
        conn = SimpleNamespace(aec_audio_cache=cache,logger=logger)
        provider,state = detector()
        trace,chunks,flags = [],[],[]
        for i in range(100):
            budget()
            tick.milliseconds = base.BASE+i*60
            if cache_enabled:
                for j in range(max(0,i-2),min(base.FRAMES+base.LEAD,i+base.LEAD+1)):
                    cache[base.BASE+j*60] = far[j*1920:(j+1)*1920]
            packet = raw[i*1920:(i+1)*1920]
            observed.clear()
            processed = probe(conn,tick.milliseconds+offset,packet)
            control = original(conn,tick.milliseconds+offset,packet)
            if warnings or type(processed) is not bytes or len(processed) != 1920 or processed != control or len(observed)>1:
                raise ValueError("probe_not_transparent_or_processing_failed")
            selection = observed[0] if observed else None
            if selection:
                ref = cache[selection["actual_reference_timestamp"]]
                if base.digest(ref) != selection["actual_reference_sha256"]:
                    raise ValueError("actual_reference_changed")
            flag = provider.is_vad(state,processed)
            if warnings or type(flag) is not bool:
                raise ValueError("vad_failed")
            if state.client_voice_stop:
                reset(state)
            chunks.append(processed)
            flags.append(flag)
            trace.append(dict(packet=i,input_pcm_sha256=base.digest(packet),output_pcm_sha256=base.digest(processed),
                vad=flag,observation=selection))
        pcm = b"".join(chunks)
        all_pcm[name] = pcm
        base.write_wave(folder/"processed.wav",pcm)
        if name in originals and (base.digest(pcm) != originals[name]["output_pcm_sha256"]
                                 or sum(flags) != originals[name]["processed"]["vad_true_packets"]):
            raise ValueError("frozen_baseline_not_reproduced")
        observations = [r["observation"] for r in trace if r["observation"]]
        suppressed = [r for r in observations if r["extra_point_three"]]
        with (folder/"trace.jsonl").open("x",encoding="utf-8",newline="\n") as stream:
            for row in trace:
                stream.write(json.dumps(row,allow_nan=False)+"\n")
        results.append(dict(case=name,has_near=has_near,has_echo=has_echo,actual_processed_packets=len(observations),
            extra_point_three_packets=len(suppressed),vad_true_packets=sum(flags),
            suppressed_corr_min=min((r["best_corr"] for r in suppressed),default=None),
            suppressed_corr_max=max((r["best_corr"] for r in suppressed),default=None),
            suppressed_abs_time_corr_max=max((abs(r["centered_time_correlation"]) for r in suppressed),default=None),
            waveform_metrics=waveform_metrics(pcm,raw,near,has_near,has_echo,np),pcm_sha256=base.digest(pcm),
            trace_sha256=base.digest((folder/"trace.jsonl").read_bytes())))
    n = np.frombuffer(near,dtype="<i2").astype(float)
    for row in results:
        if row["case"] in ("double_talk_aligned",PATH_CASES[1]):
            echo_name = PATH_CASES[0] if row["case"] == PATH_CASES[1] else "echo_only"
            delta = np.frombuffer(all_pcm[row["case"]],dtype="<i2").astype(float)-np.frombuffer(all_pcm[echo_name],dtype="<i2").astype(float)-n
            row["waveform_metrics"]["conditional_paired_near_error_energy_ratio"] = float(np.dot(delta,delta)/np.dot(n,n))
    budget()
    if any(name == "torch" or name.startswith("torch.") for name in sys.modules):
        raise ValueError("torch_imported")
    base.write_json(out/"worker-result.json",dict(state="complete",cases=results,input_scenarios=7,
        every_packet_probe_equals_original=True,probe_ast_sha256=base.digest(ast.dump(probe_node).encode()),
        worker_wall_seconds=time.monotonic()-wall,worker_cpu_seconds=time.process_time()-cpu,
        providers=session.get_providers(),numpy_version=np.__version__,onnxruntime_version=ort.__version__,warnings=warnings,
        owner_audio_used=False,live_requests=False,candidate_deployed=False,hardware_root_cause_verified=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--baseline-run",type=Path,required=True)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--max-seconds",type=float,default=120)
    parser.add_argument("--worker",action="store_true",help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 0 < args.max_seconds <= 120:
        parser.error("max-seconds must be in (0,120]")
    helper,base = load_helpers()
    if args.worker:
        worker(args,helper,base)
        return
    started = time.monotonic()
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT/"data/test-tmp").resolve()):
        parser.error("exclusive worktree data/test-tmp output required")
    args.output.mkdir(exist_ok=False)
    try:
        prepare(args,helper,base)
        remaining = min(90,args.max_seconds-(time.monotonic()-started))
        if remaining <= 0:
            raise TimeoutError("preflight_deadline")
        result = subprocess.run([sys.executable,"-I","-B","-X","utf8",str(Path(__file__).resolve()),"--worker",
            "--output",str(args.output),"--baseline-run",str(args.baseline_run),"--model",str(args.model),
            "--max-seconds",str(remaining)],cwd=ROOT,timeout=remaining,capture_output=True,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        value = (json.loads((args.output/"worker-result.json").read_text(encoding="utf-8")) if result.returncode == 0 else
                 dict(state="failed",failure_code="worker_failed",stderr_tail=result.stderr.decode("utf-8",errors="replace")[-1800:]))
    except subprocess.TimeoutExpired:
        value = dict(state="timeout",failure_code="parent_hard_wall_timeout")
    except Exception as error:
        value = dict(state="failed",failure_code=type(error).__name__,detail=str(error)[:300])
    value.update(parent_elapsed_seconds=time.monotonic()-started,parent_hard_wall_seconds=args.max_seconds,
                 output=str(args.output),harness_sha256=base.digest(Path(__file__).read_bytes()))
    base.write_json(args.output/"summary.json",value)
    print(json.dumps({key:value[key] for key in ("state","output","parent_elapsed_seconds")}))
    if value["state"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
