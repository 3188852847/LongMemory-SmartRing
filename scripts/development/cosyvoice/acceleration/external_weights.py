"""FP32图与权重分离候选。懒加载现有ONNX/numpy，不加载checkpoint或初始化CUDA。

只接受图中精确参数名；不猜测转置/折叠后的权重。发布manifest前校验全部文件。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from .capabilities import sha256

RECIPE = "external_fp32_v1"
MAX_GRAPH_BYTES = 64*2**20
MAX_DATA_BYTES = 6*2**30
MAX_CHUNK_BYTES = 4*2**20


def _chunk_size(value):
    if type(value) is not int or value < 4 or value > MAX_CHUNK_BYTES or value % 4:
        raise ValueError("fp32_chunk_bytes_must_be_multiple_of_4_up_to_4MiB")
    return value


def _safe_file(directory, name):
    if name not in {"model.onnx", "weights.bin", "manifest.json"} or directory.is_symlink():
        raise ValueError("fixed_bundle_filename_required")
    path = directory/name
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise ValueError("bundle_path_escape")
    return path


def _load_graph(path):
    import onnx
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_GRAPH_BYTES:
        raise ValueError("small_self_contained_graph_required")
    graph = onnx.load_model(str(path), load_external_data=False)
    if graph.functions or graph.graph.sparse_initializer:
        raise ValueError("functions_and_sparse_weights_not_supported")
    # 不能藏入未审查的分支图、已有外置引用或额外大权重。
    for node in graph.graph.node:
        for attribute in node.attribute:
            if attribute.type in (onnx.AttributeProto.GRAPH, onnx.AttributeProto.GRAPHS):
                raise ValueError("nested_graph_not_supported")
            if attribute.type in (onnx.AttributeProto.SPARSE_TENSOR, onnx.AttributeProto.SPARSE_TENSORS):
                raise ValueError("sparse_attribute_not_supported")
            tensors = list(attribute.tensors)
            if attribute.HasField("t"):
                tensors.append(attribute.t)
            if any(t.external_data or t.data_location == onnx.TensorProto.EXTERNAL for t in tensors):
                raise ValueError("unexpected_external_attribute")
    return graph


def _parameter_inputs(graph, runtime_names):
    names = [item.name for item in graph.graph.input]
    if len(names) != len(set(names)) or len(runtime_names) != len(set(runtime_names)):
        raise ValueError("unique_graph_inputs_required")
    if [name for name in names if name in runtime_names] != list(runtime_names):
        raise ValueError("runtime_input_names_or_order_changed")
    return [item for item in graph.graph.input if item.name not in runtime_names]


def _array_view(value, item):
    import numpy as np
    import onnx
    tensor = item.type.tensor_type
    dims = tensor.shape.dim
    if (tensor.elem_type != onnx.TensorProto.FLOAT or any(not d.HasField("dim_value") or d.dim_value <= 0 for d in dims)
            or not isinstance(value, np.ndarray) or value.dtype.str != "<f4" or not value.flags.c_contiguous
            or tuple(value.shape) != tuple(d.dim_value for d in dims) or sys.byteorder != "little"):
        raise ValueError("exact_contiguous_little_endian_fp32_parameter_required:"+item.name)
    return memoryview(value).cast("B")


def package_graph(graph_path: Path, sources: dict, runtime_names: tuple, directory: Path, *, chunk_bytes=MAX_CHUNK_BYTES,
                  cancel_check=None):
    """sources为CPU零拷贝ndarray引用；只有单块校验临时数组，绝不整权重tobytes。

    directory必须全新。异常仅unlink本次创建文件，留下failure.json；强制杀进程时无manifest即不可消费。
    """
    import numpy as np
    import onnx
    chunk_bytes = _chunk_size(chunk_bytes)
    graph = _load_graph(graph_path)
    if graph.graph.initializer:
        raise ValueError("graph_only_export_required")
    inputs = _parameter_inputs(graph, runtime_names)
    if not inputs:
        raise ValueError("no_parameter_inputs_to_externalize")
    if any(item.name not in sources for item in inputs):
        raise ValueError("unknown_parameter_mapping:"+",".join(item.name for item in inputs if item.name not in sources))
    if directory.exists() or directory.is_symlink() or not directory.parent.is_dir():
        raise ValueError("fresh_bundle_directory_required")
    directory.mkdir()
    created = []
    try:
        data_path = _safe_file(directory, "weights.bin")
        rows, total, writes, largest = [], 0, 0, 0
        digest = hashlib.sha256()
        with data_path.open("xb") as stream:
            created.append(data_path)
            for item in inputs:
                view = _array_view(sources[item.name], item)
                if not view.nbytes or total+view.nbytes > MAX_DATA_BYTES:
                    raise ValueError("external_weight_budget_exceeded")
                row = dict(name=item.name, shape=list(sources[item.name].shape), dtype="float32", offset=total, length=view.nbytes)
                parameter_digest = hashlib.sha256()
                for offset in range(0, view.nbytes, chunk_bytes):
                    if cancel_check:
                        cancel_check()
                    chunk = view[offset:offset+chunk_bytes]
                    if not np.isfinite(np.frombuffer(chunk, dtype="<f4")).all():
                        raise ValueError("nonfinite_parameter:"+item.name)
                    position = 0
                    while position < len(chunk):
                        count = stream.write(chunk[position:])
                        if not count:
                            raise OSError("external_data_short_write")
                        position += count
                        writes += 1
                        largest = max(largest, count)
                    parameter_digest.update(chunk)
                    digest.update(chunk)
                row["sha256"] = parameter_digest.hexdigest()
                rows.append(row)
                total += view.nbytes
        for row in rows:
            tensor = graph.graph.initializer.add()
            tensor.name, tensor.data_type = row["name"], onnx.TensorProto.FLOAT
            tensor.dims.extend(row["shape"])
            tensor.data_location = onnx.TensorProto.EXTERNAL
            for key, value in (("location", "weights.bin"), ("offset", str(row["offset"])), ("length", str(row["length"]))):
                entry = tensor.external_data.add()
                entry.key, entry.value = key, value
        retained = [item for item in graph.graph.input if item.name in runtime_names]
        del graph.graph.input[:]
        graph.graph.input.extend(retained)
        model_path = _safe_file(directory, "model.onnx")
        with model_path.open("xb") as stream:
            created.append(model_path)
            stream.write(graph.SerializeToString())  # 仅小图+外部引用，未装入权重raw_data。
        onnx.checker.check_model(str(model_path))
        manifest = dict(schema_version=1, recipe=RECIPE, runtime_names=list(runtime_names),
                        graph=dict(file="model.onnx", bytes=model_path.stat().st_size, sha256=sha256(model_path)),
                        data=dict(file="weights.bin", bytes=total, sha256=digest.hexdigest()), tensors=rows,
                        unused_source_names=sorted(set(sources)-{item.name for item in inputs}),
                        write_stats=dict(requested_chunk_bytes=chunk_bytes, max_write_bytes=largest, writes=writes))
        manifest_path = _safe_file(directory, "manifest.json")
        # 清单最后发布；在这之前文件不构成可消费bundle。
        verify_bundle(directory, manifest=manifest)
        serialized = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        if len(serialized) > 512*2**10:
            raise ValueError("external_manifest_too_large")
        with manifest_path.open("xb") as stream:
            created.append(manifest_path)
            stream.write(serialized)
        return dict(directory=str(directory.resolve()), manifest_sha256=sha256(manifest_path), **manifest)
    except BaseException as error:
        for path in reversed(created):
            if path.parent.resolve() != directory.resolve() or path.is_symlink():
                raise RuntimeError("owned_bundle_cleanup_path_changed") from error
            path.unlink(missing_ok=True)
        with (directory/"failure.json").open("x", encoding="utf-8") as stream:
            json.dump(dict(error=type(error).__name__, reason=str(error), complete=False), stream)
        raise


def _verify_files(directory, manifest):
    if type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1 or manifest.get("recipe") != RECIPE:
        raise ValueError("external_manifest_recipe_changed")
    if manifest["graph"]["file"] != "model.onnx" or manifest["data"]["file"] != "weights.bin":
        raise ValueError("external_bundle_filenames_changed")
    if type(manifest["data"]["bytes"]) is not int or not 0 < manifest["data"]["bytes"] <= MAX_DATA_BYTES:
        raise ValueError("external_weight_budget_exceeded")
    if type(manifest["graph"]["bytes"]) is not int or not 0 < manifest["graph"]["bytes"] <= MAX_GRAPH_BYTES:
        raise ValueError("small_self_contained_graph_required")
    model_path = _safe_file(directory, manifest["graph"]["file"])
    data_path = _safe_file(directory, manifest["data"]["file"])
    for kind, path in (("graph", model_path), ("data", data_path)):
        if path.stat().st_size != manifest[kind]["bytes"] or sha256(path) != manifest[kind]["sha256"]:
            raise ValueError("external_"+kind+"_bytes_changed")
    return model_path, data_path


def verify_bundle_files(directory: Path, expected_manifest_sha256):
    """主控制器的stdlib-only核验；不要求主环境安装ONNX或torch。"""
    manifest_path = _safe_file(directory, "manifest.json")
    if not expected_manifest_sha256 or manifest_path.stat().st_size > 512*2**10 or sha256(manifest_path) != expected_manifest_sha256:
        raise ValueError("matching_external_manifest_digest_required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _verify_files(directory, manifest)
    return manifest


def verify_bundle(directory: Path, expected_manifest_sha256=None, *, manifest=None):
    """Cosy导出环境的完整图/引用核验；不加载外部张量。"""
    import onnx
    manifest = verify_bundle_files(directory, expected_manifest_sha256) if manifest is None else manifest
    model_path, data_path = _verify_files(directory, manifest)
    graph = _load_graph(model_path)
    if [item.name for item in graph.graph.input] != manifest["runtime_names"]:
        raise ValueError("packaged_runtime_inputs_changed")
    initializers = {item.name:item for item in graph.graph.initializer}
    rows = manifest["tensors"]
    if len(initializers) != len(graph.graph.initializer) or len(rows) != len(initializers) or {row["name"] for row in rows} != set(initializers):
        raise ValueError("external_initializer_set_changed")
    cursor = 0
    with data_path.open("rb") as stream:
        for row in rows:
            tensor = initializers[row["name"]]
            metadata = {entry.key:entry.value for entry in tensor.external_data}
            if (any((tensor.raw_data,tensor.float_data,tensor.int32_data,tensor.int64_data,tensor.double_data,tensor.string_data,tensor.uint64_data))
                    or tensor.data_type != onnx.TensorProto.FLOAT or row["dtype"] != "float32" or len(tensor.external_data) != 3
                    or tensor.data_location != onnx.TensorProto.EXTERNAL or list(tensor.dims) != row["shape"]
                    or row["offset"] != cursor or type(row["length"]) is not int or row["length"] <= 0
                    or metadata != dict(location="weights.bin", offset=str(cursor), length=str(row["length"]))):
                raise ValueError("external_tensor_reference_changed")
            size = 4
            for dim in row["shape"]:
                if type(dim) is not int or dim <= 0:
                    raise ValueError("external_tensor_shape_invalid")
                size *= dim
            if size != row["length"] or cursor+size > manifest["data"]["bytes"]:
                raise ValueError("external_tensor_length_changed")
            remaining, digest = size, hashlib.sha256()
            while remaining:
                block = stream.read(min(remaining, MAX_CHUNK_BYTES))
                if not block:
                    raise ValueError("truncated_external_tensor")
                digest.update(block)
                remaining -= len(block)
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("external_parameter_digest_changed")
            cursor += size
    if cursor != manifest["data"]["bytes"]:
        raise ValueError("unexpected_external_trailing_data")
    return model_path


def export_module(model, example, directory: Path, *, input_names, output_names, dynamic_axes, opset=18,
                  chunk_bytes=MAX_CHUNK_BYTES, cancel_check=None):
    """仅已加载的自有CPU FP32实例；不读模型文件、不调.cuda，不替换参数或改变依赖。"""
    import torch
    if torch.__version__ != "2.3.1+cu121":
        raise ValueError("fixed_exporter_torch_2_3_1_required")
    if opset not in (17,18) or any(module.training for module in model.modules()):
        raise ValueError("eval_module_and_reviewed_opset_required")
    if any(value.device.type != "cpu" or value.dtype != torch.float32 for value in model.parameters()):
        raise ValueError("cpu_fp32_module_required")
    if any(value.device.type != "cpu" for value in model.buffers()):
        raise ValueError("cpu_buffers_required")
    if any(value.device.type != "cpu" or value.dtype != torch.float32 for value in example):
        raise ValueError("cpu_fp32_example_required")
    if directory.exists() or directory.is_symlink():
        raise ValueError("new_export_directory_required")
    directory.mkdir()
    graph_path = directory/"graph-only.onnx"
    with torch.no_grad():
        torch.onnx.export(model, example, str(graph_path), export_params=False, keep_initializers_as_inputs=True,
                          do_constant_folding=False, opset_version=opset, input_names=list(input_names),
                          output_names=list(output_names), dynamic_axes=dynamic_axes)
    sources = {}
    for name, value in list(model.named_parameters(remove_duplicate=False))+list(model.named_buffers(remove_duplicate=False)):
        if name in sources or value.device.type != "cpu":
            raise ValueError("unique_cpu_weight_sources_required")
        sources[name] = value.detach().numpy()
    return package_graph(graph_path, sources, tuple(input_names), directory/"package", chunk_bytes=chunk_bytes,
                         cancel_check=cancel_check)
