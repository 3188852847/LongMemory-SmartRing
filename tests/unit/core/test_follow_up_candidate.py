from datetime import UTC, datetime, timedelta

import pytest

from longmemory.core.proactive import FollowUpCandidate, FollowUpCandidateStatus


NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def build_candidate(**changes):
    values = {
        "id": "a" * 32,
        "subject_id": "user:self",
        "source_memory_id": "memory-1",
        "source_content_sha256": "b" * 64,
        "prompt_text": "毕业设计汇报准备得怎么样了？",
        "follow_up_at": NOW + timedelta(days=1),
        "status": FollowUpCandidateStatus.CANDIDATE,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return FollowUpCandidate(**values)


def test_follow_up_candidate_requires_future_aware_time_and_clean_prompt():
    assert build_candidate().status is FollowUpCandidateStatus.CANDIDATE
    with pytest.raises(ValueError, match="follow_up_time_not_future"):
        build_candidate(follow_up_at=NOW)
    with pytest.raises(ValueError, match="follow_up_prompt_invalid"):
        build_candidate(prompt_text=" 含有前导空格")
    with pytest.raises(ValueError, match="follow_up_source_digest_invalid"):
        build_candidate(source_content_sha256="not-a-digest")
