from longmemory.infrastructure.config.memory_backends import MemoryBackendStore


def test_legacy_process_is_reported_without_offering_legacy_startup():
    state = MemoryBackendStore(current_backend="longmemory").describe()
    assert state["current_backend"] == "longmemory"
    assert state["next_start_backend"] == "hy_memory"
    assert state["restart_required"]
