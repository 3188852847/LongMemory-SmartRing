"""在固定Cosy环境、自有CPU Job内执行的微型模型契约；不用pytest或真实checkpoint。"""

import sys
if __name__ == "__main__":
    sys.stdin.buffer.read()  # 父进程Assign后才放行，包括第三方包导入。

import hashlib
import json
import os
from pathlib import Path
import socket
import unittest
import warnings

def denied(*args, **kwargs):
    raise RuntimeError("CPU_suite_forbids_network_cuda_and_checkpoint_loading")

assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""
socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = denied
socket.getaddrinfo = socket.create_connection = denied
import numpy as np
import onnx
import onnxruntime as ort
import torch

assert (torch.__version__,np.__version__,onnx.__version__,ort.__version__) == ("2.3.1+cu121","1.26.4","1.16.0","1.18.0")
torch.cuda._lazy_init = torch.cuda.init = torch.load = torch.jit.load = denied
torch.set_num_threads(2)
torch.set_num_interop_threads(1)
torch.random.default_generator.manual_seed(17)
sys.path.insert(0, sys.argv[1])
from acceleration import external_weights as external

OUTPUT = Path(sys.argv[2])
OBSERVATIONS = []


class ExternalWeightsCPU(unittest.TestCase):
    def setUp(self):
        self.path = OUTPUT/self._testMethodName
        self.path.mkdir()

    def graph(self, *, name="w", shape=(2,2), dtype=onnx.TensorProto.FLOAT):
        graph = onnx.helper.make_graph([onnx.helper.make_node("MatMul", ["x",name], ["y"])], "tiny",
                  [onnx.helper.make_tensor_value_info("x",onnx.TensorProto.FLOAT,["N",2]),
                   onnx.helper.make_tensor_value_info(name,dtype,list(shape))],
                  [onnx.helper.make_tensor_value_info("y",onnx.TensorProto.FLOAT,["N",2])])
        model = onnx.helper.make_model(graph,opset_imports=[onnx.helper.make_opsetid("",17)])
        path = self.path/"graph.onnx"
        onnx.save(model,str(path))
        return path

    def package(self, source=None, **kwargs):
        source = {"w":np.arange(4,dtype=np.float32).reshape(2,2)} if source is None else source
        return external.package_graph(self.graph(),source,("x",),self.path/"package",chunk_bytes=8,**kwargs)

    def test_streamed_bytes_and_cpu_numeric(self):
        bundle = self.package()
        folder = Path(bundle["directory"])
        model = external.verify_bundle(folder,bundle["manifest_sha256"])
        parsed = onnx.load(str(model),load_external_data=False)
        self.assertEqual([x.name for x in parsed.graph.input],["x"])
        self.assertFalse(parsed.graph.initializer[0].raw_data)
        self.assertEqual(bundle["write_stats"]["max_write_bytes"],8)
        self.assertEqual(bundle["write_stats"]["writes"],2)
        session = ort.InferenceSession(str(model),providers=["CPUExecutionProvider"])
        session.disable_fallback()
        self.assertEqual(session.get_providers(),["CPUExecutionProvider"])
        x=np.array([[1,2],[3,4]],dtype=np.float32)
        np.testing.assert_array_equal(session.run(None,{"x":x})[0],x@np.arange(4,dtype=np.float32).reshape(2,2))

    def test_unknown_mapping_refuses_before_output(self):
        with self.assertRaisesRegex(ValueError,"unknown_parameter_mapping"):
            external.package_graph(self.graph(name="onnx::MatMul_32"),{"w":np.ones((2,2),np.float32)},("x",),self.path/"package")
        self.assertFalse((self.path/"package").exists())

    def test_wrong_shape_dtype_and_noncontiguous_refuse(self):
        for index,value in enumerate((np.ones((4,),np.float32),np.ones((2,2),np.float16),np.ones((2,2),np.float32).T)):
            with self.subTest(index=index),self.assertRaisesRegex(ValueError,"exact_contiguous"):
                external.package_graph(self.graph(),{"w":value},("x",),self.path/f"bad-{index}")
            self.assertFalse((self.path/f"bad-{index}/weights.bin").exists())

    def test_symbolic_parameter_shape_refuses(self):
        with self.assertRaisesRegex(ValueError,"exact_contiguous"):
            external.package_graph(self.graph(shape=("K",2)),{"w":np.ones((2,2),np.float32)},("x",),self.path/"package")

    def test_nonfinite_partial_data_cleaned(self):
        value=np.arange(4,dtype=np.float32).reshape(2,2);value[-1,-1]=np.nan
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            self.package({"w":value})
        folder=self.path/"package"
        self.assertEqual({p.name for p in folder.iterdir()},{"failure.json"})

    def test_cancel_removes_only_owned_partial_files(self):
        calls=[]
        def cancel():
            calls.append(True)
            if len(calls)==2:raise InterruptedError("synthetic_cancel")
        unrelated=self.path/"unrelated.bin";unrelated.write_bytes(b"preserve")
        with self.assertRaises(InterruptedError):self.package(cancel_check=cancel)
        self.assertEqual(unrelated.read_bytes(),b"preserve")
        self.assertEqual({p.name for p in (self.path/"package").iterdir()},{"failure.json"})

    def test_existing_directory_never_overwritten(self):
        folder=self.path/"package";folder.mkdir();(folder/"weights.bin").write_bytes(b"existing")
        with self.assertRaisesRegex(ValueError,"fresh_bundle"):self.package()
        self.assertEqual((folder/"weights.bin").read_bytes(),b"existing")

    def test_input_order_mismatch_refuses(self):
        with self.assertRaisesRegex(ValueError,"runtime_input"):
            external.package_graph(self.graph(),{},("missing",),self.path/"package")

    def test_manifest_digest_and_data_tampering_refuse(self):
        bundle=self.package();folder=Path(bundle["directory"])
        with self.assertRaisesRegex(ValueError,"manifest_digest"):external.verify_bundle(folder,"0"*64)
        with (folder/"weights.bin").open("r+b") as stream:stream.write(b"changed!")
        with self.assertRaisesRegex(ValueError,"data_bytes_changed"):external.verify_bundle(folder,bundle["manifest_sha256"])

    def test_unsafe_external_path_and_offset_refuse(self):
        bundle=self.package();folder=Path(bundle["directory"])
        for field,value in (("file","../outside.bin"),("offset",4),("sha256","0"*64)):
            manifest=json.loads((folder/"manifest.json").read_text())
            if field=="file":manifest["data"][field]=value
            else:manifest["tensors"][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):external.verify_bundle(folder,manifest=manifest)

    def test_graph_with_preexisting_initializer_refuses(self):
        path=self.graph();model=onnx.load(str(path));model.graph.initializer.append(onnx.numpy_helper.from_array(np.ones((2,2),np.float32),"w"));onnx.save(model,str(path))
        with self.assertRaisesRegex(ValueError,"graph_only"):external.package_graph(path,{},("x",),self.path/"package")

    def test_graph_reference_escape_rejected_without_loading_external_bytes(self):
        bundle=self.package();folder=Path(bundle["directory"])
        model_path=folder/"model.onnx";model=onnx.load(str(model_path),load_external_data=False)
        model.graph.initializer[0].external_data[0].value="../outside.bin"
        model_path.write_bytes(model.SerializeToString())
        manifest=json.loads((folder/"manifest.json").read_text())
        manifest["graph"].update(bytes=model_path.stat().st_size,sha256=external.sha256(model_path))
        with self.assertRaisesRegex(ValueError,"reference_changed"):external.verify_bundle(folder,manifest=manifest)

    def test_data_budget_refusal_cleans_owned_partial(self):
        original=external.MAX_DATA_BYTES;external.MAX_DATA_BYTES=8
        try:
            with self.assertRaisesRegex(ValueError,"budget"):self.package()
        finally:external.MAX_DATA_BYTES=original
        self.assertEqual({p.name for p in (self.path/"package").iterdir()},{"failure.json"})

    def test_invalid_chunk_budgets_refuse(self):
        for value in (0,3,5,external.MAX_CHUNK_BYTES+4):
            with self.subTest(value=value),self.assertRaises(ValueError):external.package_graph(self.graph(),{},("x",),self.path/str(value),chunk_bytes=value)

    def test_torch_tiny_export_opsets17_18_externalized(self):
        class Toy(torch.nn.Module):
            def __init__(self):
                super().__init__();self.linear=torch.nn.Linear(8,8);self.norm=torch.nn.LayerNorm(8)
            def forward(self,x,mask):
                h=self.norm(self.linear(x)).unsqueeze(1)
                return torch.nn.functional.scaled_dot_product_attention(h,h,h,attn_mask=mask,dropout_p=0.).squeeze(1)
        model=Toy().cpu().float().eval()
        original={name:value.detach().clone() for name,value in model.named_parameters()}
        def inputs(n,padded=False):
            x=torch.arange(2*n*8,dtype=torch.float32).reshape(2,n,8)/100
            mask=torch.zeros((2,1,n,n),dtype=torch.float32)
            if padded:mask[:,:,:,-1]=-10000
            return x,mask
        for opset in (17,18):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                bundle=external.export_module(model,inputs(3),self.path/f"opset{opset}",input_names=("x","mask"),output_names=("y",),
                    dynamic_axes={"x":{1:"N"},"mask":{2:"N",3:"N"},"y":{1:"N"}},opset=opset,chunk_bytes=64)
            folder=Path(bundle["directory"]);path=external.verify_bundle(folder,bundle["manifest_sha256"])
            options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
            session=ort.InferenceSession(str(path),sess_options=options,providers=["CPUExecutionProvider"]);session.disable_fallback()
            checks=[]
            for n in (3,5):
                for padded in (False,True):
                    x,mask=inputs(n,padded)
                    with torch.no_grad():expected=model(x,mask).numpy()
                    actual=session.run(None,{"x":x.numpy(),"mask":mask.numpy()})[0]
                    np.testing.assert_allclose(actual,expected,rtol=1e-4,atol=1e-5)
                    checks.append(dict(length=n,padded=padded,max_abs_error=float(np.max(np.abs(actual-expected)))))
            OBSERVATIONS.append(dict(opset=opset,checks=checks,manifest_sha256=bundle["manifest_sha256"],
                data_bytes=bundle["data"]["bytes"],write_stats=bundle["write_stats"],providers=session.get_providers(),
                warnings=[str(w.message) for w in caught]))
        for name,value in model.named_parameters():self.assertTrue(torch.equal(value,original[name]))
        self.assertFalse(model.training)


if __name__ == "__main__":
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExternalWeightsCPU))
    report=dict(tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),observations=OBSERVATIONS,
                torch=torch.__version__,onnx=onnx.__version__,onnxruntime=ort.__version__,numpy=np.__version__,
                real_flow_loaded=False,cuda_initialized=torch.cuda.is_initialized())
    (OUTPUT/"cpu-suite.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    raise SystemExit(not result.wasSuccessful())
