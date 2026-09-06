import pytest

from longmemory.methods.contracts import ObservationResult


def test_source_only_requires_warning_and_completed_forbids_warning():
    with pytest.raises(ValueError):
        ObservationResult("event", (), processing_status="source_only")
    with pytest.raises(ValueError):
        ObservationResult("event", (), warning_code="unexpected")
