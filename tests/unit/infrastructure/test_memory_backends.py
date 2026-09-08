from longmemory.infrastructure.config.memory_backends import MemoryBackendStore


def test_memory_backend_selection_is_non_secret_and_defaults_to_longmemory(tmp_path):
    store = MemoryBackendStore(tmp_path, current_backend="longmemory")
    assert store.selected() == "longmemory"
    result = store.select("xiaozhi_local")
    assert result["next_start_backend"] == "xiaozhi_local"
    assert result["restart_required"] is True
    assert "api_key" not in store.selection_path.read_text(encoding="utf-8").lower()

    store.selection_path.write_text('{"selected_backend":"unknown"}', encoding="utf-8")
    assert store.selected() == "longmemory"
