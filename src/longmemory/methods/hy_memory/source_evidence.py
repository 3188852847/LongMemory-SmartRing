"""按2.0.3公开ID/结构化版本重读来源，不把链头meta冒充整个画像/历史。"""

from copy import deepcopy
import json

from .sdk_bridge import _sources
from .observation import measured


def _complete_meta(row):
    meta=row.get("meta")
    try:return meta if _sources(meta) else None
    except (ValueError,RuntimeError):return None


@measured('source_enrich_ms')
def enrich_search(client,response,user_ids):
    result=deepcopy(response)
    channels=result.get("memories",{})
    if not isinstance(channels,dict):return result
    cache={}
    for memories in channels.values():
        if not isinstance(memories,list):continue
        for memory in memories:
            chain=memory.get("evolution_chain")
            if not chain:continue
            meta=[];complete=isinstance(chain,list) and len(chain)<=1000
            for version in chain if complete else []:
                node_id=version.get("node_id")
                try:
                    if node_id not in cache:cache[node_id]=client.get(node_id)
                    row=cache[node_id]
                    if (not isinstance(row,dict) or row.get("memory_id")!=node_id or row.get("user_id") not in user_ids
                            or row.get("content")!=version.get("content") or not _complete_meta(row)):
                        complete=False;break
                    meta.extend(row["meta"])
                except Exception:complete=False;break
            memory["meta"]=list({json.dumps(item,sort_keys=True):item for item in meta}.values()) if complete else None
            memory["source_trace_status"]="all_visible_versions" if complete else "unknown_version_source"
    return result


@measured('source_enrich_ms')
def enrich_profile(client,response,user_id):
    result=deepcopy(response);profile=result.get("profile")
    if not isinstance(profile,dict) or not isinstance(profile.get("basic_info"),dict) or "meta" in profile:return result
    profile["meta"]=None;profile["source_trace_status"]="unknown_aggregate_source"
    # Ultra目录/补充并非这些基本字段的来源，本适配不冒称覆盖。
    if any(profile.get(name,{}).get("attached") for name in ("catalog","supplement")):return result
    try:
        info=client.get_user_basic_info(user_id=user_id)
        heads=info["memories"]
        if len(heads)!=1 or heads[0]["memory_id"]!=profile["memory_id"]:return result
        head=heads[0]
        chain=head.get("evolution_chain") or [{"node_id":head["memory_id"]}]
        if not isinstance(chain,list) or not 1<=len(chain)<=1000:return result
        # SDK链已按完整时间/拓扑排好latest→oldest。不要用截为秒的公开时间
        # 另猜顺序，也不把旧location的来源绑定到新location。
        assembled={};origins={}
        for version in reversed(chain):
            node_id=version["node_id"];row=client.get(node_id)
            if row.get("memory_id")!=node_id or row.get("user_id")!=user_id or row.get("layer")!="l0_basic_info":return result
            kv=row.get("custom",{}).get("basic_info_kv")
            if not isinstance(kv,dict):return result
            for key,value in kv.items():
                assembled[key]=value;origins[key]=row
        if assembled!=profile["basic_info"]:return result
        evidence={key:{"memory_id":row["memory_id"],"source_event_ids":_sources(_complete_meta(row))} for key,row in origins.items()}
        profile["field_sources"]=evidence
        if any(not item["source_event_ids"] for item in evidence.values()):return result
        meta=[]
        for row in origins.values():meta.extend(row["meta"])
        profile["meta"]=list({json.dumps(item,sort_keys=True):item for item in meta}.values())
        profile["source_trace_status"]="all_current_fields"
    except Exception:
        # 来源不足保持unknown，不用正文相似/头节点身份填补。
        pass
    return result
