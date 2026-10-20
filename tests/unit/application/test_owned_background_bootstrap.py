"""真实owned网关/账本装配＋SDK构造替身；不加载SDK、CPU模型或供应商。"""

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from longmemory import bootstrap
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"tests/integration"))
from test_hy_daily_lifecycle import arrange, assert_closed


@pytest.mark.parametrize("semantic", [False,True])
def test_owned_bootstrap_enables_only_ephemeral_semantic_background_lane(tmp_path,monkeypatch,semantic):
    open_runtime,gateways,deployment,budget = arrange(tmp_path)
    deployment.settings = replace(deployment.settings,semantic_layers_enabled=semantic)
    prototype = deployment.settings
    seen = []
    class Runtime:
        def attach_model_service(self,owned): self.owned = owned
        def close(self): self.owned.close()
    def build(**kwargs):
        seen.append(kwargs)
        assert gateways[-1].thread.is_alive()
        return Runtime()
    monkeypatch.setattr(bootstrap,"build_hy_memory_runtime",build)
    runtime = open_runtime(True)
    try:
        settings = seen[0]["settings"]
        assert settings.background_priority_enabled is semantic
        assert not prototype.background_priority_enabled
        assert settings.identity() == prototype.identity()
        assert settings.llm.base_url.endswith("/hy/v1")
        assert settings.embedding.base_url == settings.llm.base_url
        assert settings.llm.api_key == gateways[-1].token
        assert gateways[-1].background_readiness()["eligible"]
        assert budget.report()["attempt_count"] == 1  # 仅arrange已有的合成原账本记录。
    finally:
        runtime.close()
    assert_closed(gateways[-1])
