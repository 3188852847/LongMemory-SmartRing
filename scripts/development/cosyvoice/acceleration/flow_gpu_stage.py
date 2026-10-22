"""ROOT在另行授权的GPU窗口调用：复用CPU产物构建引擎并执行一次真实参考输入。"""

import argparse
import json
from pathlib import Path
import os
import subprocess

from .capabilities import sha256
from .external_weights import verify_bundle_files
from .flow_trtexec import build_command
from .native_flow import NativeFlowWorker


def execute(cpu_output, worker_path, sdk, toolkit, output, *, existing_engine=None, reference_path=None):
    exported=json.loads((cpu_output/"export.json").read_text(encoding="utf-8"))
    verify_bundle_files(cpu_output/"external-candidate/package",exported["bundle"]["manifest_sha256"])
    output.mkdir(parents=True,exist_ok=False)
    engine=existing_engine if existing_engine is not None else output/"flow.fp32.plan"
    if existing_engine is None:
        argv=build_command(sdk,cpu_output,"external_fp32_v1")
        replacements={"--saveEngine=":str(engine),"--exportLayerInfo=":str(output/"layers.json")}
        for i,value in enumerate(argv):
            for prefix,replacement in replacements.items():
                if value.startswith(prefix):argv[i]=prefix+replacement
        env=dict(os.environ)
        env["PATH"]=os.pathsep.join((str(sdk/"bin"),str(toolkit/"bin/x64"),env.get("PATH","")))
        print("Building TensorRT11 Flow engine",flush=True)
        with (output/"build.log").open("xb") as log:
            subprocess.run(argv,env=env,cwd=output,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
    import numpy as np
    from .flow_trtexec import NAMES,shapes
    case=cpu_output/"n128-full"
    values=[np.fromfile(case/(name+".bin"),dtype="<f4").reshape(shape) for name,shape in shapes(128).items()]
    native=NativeFlowWorker(engine_path=engine,worker_path=worker_path,sdk_root=sdk,toolkit_root=toolkit)
    try:
        result=native.infer(values)
    finally:
        native.close()
    reference_path=reference_path if reference_path is not None else case/"expected.bin"
    expected=np.fromfile(reference_path,dtype="<f4").reshape(2,80,128)
    result.tofile(output/"estimator_out.bin")
    delta=np.abs(result-expected)
    comparison=dict(reference_allclose=bool(np.allclose(result,expected,rtol=1e-2,atol=1e-4)),
                    reference_path=str(reference_path.resolve()),max_abs_error=float(delta.max()),
                    mismatched=int((delta>1e-4+1e-2*np.abs(expected)).sum()),elements=int(result.size))
    (output/"comparison.json").write_text(json.dumps(comparison,indent=2),encoding="utf-8")
    np.testing.assert_allclose(result,expected,rtol=1e-2,atol=1e-4)
    identity=dict(engine_path=str(engine.resolve()),engine_sha256=sha256(engine),precision="fp32",
                  source_commit=exported["source_commit"],graph_streaming=exported["streaming"],
                  external_manifest_sha256=exported["bundle"]["manifest_sha256"],reference_allclose=True,
                  reference_path=str(reference_path.resolve()),max_abs_error=float(np.max(np.abs(result-expected))))
    (output/"engine.json").write_text(json.dumps(identity,indent=2),encoding="utf-8")
    print(json.dumps(identity),flush=True)
    return identity


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("cpu-output","worker","sdk","toolkit","output"):parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--engine",type=Path,help="复用已写出的engine，不调用trtexec")
    parser.add_argument("--reference",type=Path,help="同一n128输入的明确参考文件")
    args=parser.parse_args()
    execute(args.cpu_output,args.worker,args.sdk,args.toolkit,args.output,existing_engine=args.engine,reference_path=args.reference)
