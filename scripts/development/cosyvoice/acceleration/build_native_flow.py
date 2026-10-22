"""只编译SDK11 Flow worker，不运行它或加载CUDA驱动。"""

import argparse
from pathlib import Path
import subprocess


def build(sdk, toolkit, output):
    output.mkdir(parents=True,exist_ok=False)
    vswhere=Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe")
    visual_studio=subprocess.check_output([str(vswhere),"-latest","-products","*","-requires","Microsoft.VisualStudio.Component.VC.Tools.x86.x64","-property","installationPath"],text=True).strip()
    vcvars=Path(visual_studio)/"VC/Auxiliary/Build/vcvars64.bat"
    args=["/nologo","/std:c++17","/EHsc","/O2","/utf-8",str(Path(__file__).with_name("flow_trt11_worker.cpp")),
          "/I"+str(sdk/"include"),"/I"+str(toolkit/"include"),"/Fe:flow_trt11_worker.exe","/Fo:flow_trt11_worker.obj",
          "/link","/LIBPATH:"+str(sdk/"lib"),"/LIBPATH:"+str(toolkit/"lib/x64"),
          "nvinfer_11.lib","nvinfer_plugin_11.lib","cudart.lib"]
    (output/"worker.rsp").write_text(subprocess.list2cmdline(args),encoding="utf-16")
    (output/"build.cmd").write_text('@echo off\ncall "'+str(vcvars)+'" >nul\nif errorlevel 1 exit /b %errorlevel%\ncl @worker.rsp\n',encoding="ascii")
    subprocess.run(["cmd.exe","/d","/c","build.cmd"],cwd=output,check=True)
    return output/"flow_trt11_worker.exe"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("sdk","toolkit","output"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    print(build(args.sdk,args.toolkit,args.output))
