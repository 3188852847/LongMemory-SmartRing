import json
import math

import pytest

from longmemory.core.memory.retrieval.vector import ExactVectorIndex, VectorDocument, unit_vector


def doc(name):
    return VectorDocument(name, "合成条目" + name, ("source-" + name,))


def test_cosine_rank_ties_threshold_and_restart(tmp_path):
    docs = [doc("a"), doc("b"), doc("c")]
    index = ExactVectorIndex(docs, [[3, 0], [0, 2], [9, 0]], encoder_id="fake")
    assert [d.item_id for d, _ in index.search([1, 0])] == ["a", "c", "b"]
    assert len(index.search([1, 0], min_score=0.5)) == 2
    assert index.search([-1, -1], min_score=0.5) == ()
    path = tmp_path / "index.json"
    index.save(path)
    before = path.read_bytes()
    restored = ExactVectorIndex.load(path, encoder_id="fake")
    assert restored.search([1, 0]) == index.search([1, 0])
    assert path.read_bytes() == before
    with pytest.raises(FileExistsError):
        index.save(path)
    with pytest.raises(ValueError):
        ExactVectorIndex.load(path, encoder_id="different-model")
    payload = json.loads(before)
    payload["payload"]["documents"][0]["content"] = "篡改"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        ExactVectorIndex.load(path, encoder_id="fake")


@pytest.mark.parametrize("values", [[], [0, 0], [math.nan], [math.inf], [True], ["1"]])
def test_invalid_vectors_fail(values):
    with pytest.raises(ValueError):
        unit_vector(values)


def test_dimensions_count_and_duplicate_ids():
    with pytest.raises(ValueError):
        ExactVectorIndex([doc("a")], [], encoder_id="fake")
    with pytest.raises(ValueError):
        ExactVectorIndex([doc("a"), doc("b")], [[1], [1, 1]], encoder_id="fake")
    with pytest.raises(ValueError):
        ExactVectorIndex([doc("a"), doc("a")], [[1], [1]], encoder_id="fake")
    index = ExactVectorIndex([doc("a")], [[1]], encoder_id="fake")
    with pytest.raises(ValueError):
        index.search([1, 2])
    for threshold in [math.nan, math.inf, 2, True]:
        with pytest.raises(ValueError):
            index.search([1], min_score=threshold)


def test_empty_corpus_makes_no_document_encoding_request():
    class NoCall:
        def encode_documents(self, texts):
            raise AssertionError("empty corpus should not encode")
    index = ExactVectorIndex.build([], NoCall(), encoder_id="fake")
    assert index.search([1, 0]) == ()


def test_document_requires_provenance():
    for sources in [(), ("",), ("e01", "e01")]:
        with pytest.raises(ValueError):
            VectorDocument("a", "文本", sources)
