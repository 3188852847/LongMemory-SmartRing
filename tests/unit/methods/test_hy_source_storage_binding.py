"""Hy来源格式兼容精确白名单；不改公共装配或真实来源身份。"""

import json
import sqlite3

import pytest

from longmemory.methods.hy_memory.method import HyMemoryMethod
from longmemory.methods.hy_memory.settings import HySettings
from longmemory.methods.hy_memory.assembly import _source_storage_identity,assemble_hy_backend,management_primitives_identity
from longmemory.methods.backend_contracts import StateResource


def method(semantic=False):
    return HyMemoryMethod(settings=HySettings(user_id="ab-binding",semantic_layers_enabled=semantic),client_factory=lambda:None)


def test_only_known_runtime_versions_share_stable_storage_identity():
    old,new = method(),method(True)
    assert old.implementation_version == "sdk-2.0.3-adapter-1"
    assert new.implementation_version == "sdk-2.0.3-semantic-adapter-2"
    assert old.source_storage_version == new.source_storage_version == old.implementation_version
    new.implementation_version = "sdk-2.0.3-semantic-adapter-99"
    with pytest.raises(ValueError,match="unproven"):
        _ = new.source_storage_version


@pytest.mark.parametrize("version",["sdk-2.0.3-adapter-1","sdk-2.0.3-semantic-adapter-2"])
def test_known_old_binding_is_returned_byte_for_byte_without_identity_update(tmp_path,version):
    source=tmp_path/"source.db"
    resources=(StateResource("hy_state",tmp_path/"engine","directory"),)
    text=json.dumps({"method":"hy_memory_pro_chat","version":version,
        "resources":[["hy_state",str((tmp_path/"engine").resolve()),"directory"]]},sort_keys=True)
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE source_journal_identity(engine_name TEXT)")
        db.execute("INSERT INTO source_journal_identity VALUES (?)",(text,))
    before=source.read_bytes()
    assert _source_storage_identity(method(True),resources,source,create=False)==text
    assert _source_storage_identity(method(False),resources,source,create=False)==text
    assert source.read_bytes()==before


@pytest.mark.parametrize("change",["version","method","resources","extra"])
def test_unknown_version_method_resource_or_extra_metadata_still_refused(tmp_path,change):
    source=tmp_path/"source.db"
    resources=(StateResource("hy_state",tmp_path/"engine","directory"),)
    body={"method":"hy_memory_pro_chat","version":"sdk-2.0.3-adapter-1",
        "resources":[["hy_state",str((tmp_path/"engine").resolve()),"directory"]]}
    if change=="version":body[change]="sdk-2.0.4-adapter-1"
    elif change=="method":body[change]="another_engine"
    elif change=="resources":body[change]=[["hy_state",str(tmp_path/"other"),"directory"]]
    else:body["future_contract"]=True
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE source_journal_identity(engine_name TEXT)")
        db.execute("INSERT INTO source_journal_identity VALUES (?)",(json.dumps(body,sort_keys=True),))
    before=source.read_bytes()
    with pytest.raises(ValueError,match="source_journal_engine_mismatch"):
        _source_storage_identity(method(True),resources,source,create=False)
    assert source.read_bytes()==before


def test_old_proof_cannot_use_storage_compatibility_to_enable_background(tmp_path):
    settings=HySettings(user_id="ab-binding",semantic_layers_enabled=True)
    with pytest.raises(ValueError,match="verification"):
        assemble_hy_backend(settings=settings,state_directory=tmp_path/"engine",source_path=tmp_path/"source.db",
            create=True,client_factory=lambda *a,**kw:None,management_verification={"sdk_version":"2.0.3",
                "rpc_source_sha256":management_primitives_identity(),"real_sdk_rpc_verified":True,"semantic_background_writes_disabled":True})
    assert not (tmp_path/"engine").exists() and not (tmp_path/"source.db").exists()
