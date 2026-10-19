from copy import deepcopy

from longmemory.methods.hy_memory.source_evidence import enrich_profile,enrich_search
from longmemory.methods.hy_memory.sdk_bridge import SOURCE_NAMESPACE


def node(nid,content,eid,kv=None):
    return {"memory_id":nid,"user_id":"synthetic","content":content,"layer":"l0_basic_info" if kv else "l2_fact",
        "custom":{"basic_info_kv":kv} if kv else {},"meta":[{"namespace":SOURCE_NAMESPACE,"source_event_ids":[eid]}]}


def test_evolution_bundle_collects_all_actual_versions_not_head_only():
    rows={"new":node("new","新事实","e2"),"old":node("old","旧事实","e1")}
    class Client:
        def get(self,nid):return rows[nid]
    response={"memories":{"normal":[{"memory_id":"new","content":"新旧整条链","meta":rows['new']['meta'],
        "evolution_chain":[{"node_id":"new","content":"新事实"},{"node_id":"old","content":"旧事实"}]}]}}
    result=enrich_search(Client(),response,["synthetic"])
    assert {item['source_event_ids'][0] for item in result['memories']['normal'][0]['meta']}=={"e1","e2"}
    rows['old']['meta']=[]
    assert enrich_search(Client(),response,["synthetic"])['memories']['normal'][0]['meta'] is None


def test_profile_sources_follow_current_structured_fields_not_old_location():
    rows={"name":node("name","姓名","e1",{"name":"甲"}),"old":node("old","旧城市","e2",{"location":"旧市"}),"head":node("head","新城市","e3",{"location":"新市"})}
    class Client:
        def get(self,nid):return rows[nid]
        def get_user_basic_info(self,**kwargs):return {"memories":[{"memory_id":"head","evolution_chain":[{"node_id":"head"},{"node_id":"old"},{"node_id":"name"}]}]}
    profile={"profile":{"memory_id":"head","content":"当前甲在新市","basic_info":{"name":"甲","location":"新市"}}}
    result=enrich_profile(Client(),profile,"synthetic")['profile']
    assert result['field_sources']['name']['source_event_ids']==('e1',)
    assert result['field_sources']['location']['source_event_ids']==('e3',)
    assert {item['source_event_ids'][0] for item in result['meta']}=={'e1','e3'}
    inconsistent=deepcopy(profile);inconsistent['profile']['basic_info']['location']='不一致'
    assert enrich_profile(Client(),inconsistent,'synthetic')['profile']['meta'] is None
