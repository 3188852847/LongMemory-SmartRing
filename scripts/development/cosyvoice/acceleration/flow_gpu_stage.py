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


def execute(cpu_output, worker_path, sdk, toolkit, output):
    exported=json.loads((cpu_output/"export.json").read_text(encoding="utf-8"))
    verify_bundle_files(cpu_output/"external-candidate/package",exported["bundle"]["manifest_sha256"])
    output.mkdir(parents=True,exist_ok=False)
    engine=output/"flow.fp32.plan"
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
    expected=np.fromfile(case/"expected.bin",dtype="<f4").reshape(2,80,128)
    np.testing.assert_allclose(result,expected,rtol=1e-2,atol=1e-4)
    identity=dict(engine_path=str(engine.resolve()),engine_sha256=sha256(engine),precision="fp32",
                  source_commit=exported["source_commit"],graph_streaming=exported["streaming"],
                  external_manifest_sha256=exported["bundle"]["manifest_sha256"],reference_allclose=True,
                  max_abs_error=float(np.max(np.abs(result-expected))))
    (output/"engine.json").write_text(json.dumps(identity,indent=2),encoding="utf-8")
    print(json.dumps(identity),flush=True)
    return identity


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("cpu-output","worker","sdk","toolkit","output"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    execute(args.cpu_output,args.worker,args.sdk,args.toolkit,args.output)
