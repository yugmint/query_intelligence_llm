"""
Tests for VectorStoreFactory.load's "no index yet" handling
(src/retrieval/vectorstore.py). Doesn't need a real embedding model --
the missing-index check happens before FAISS.load_local is ever called.
"""

from src.retrieval.vectorstore import VectorStoreFactory


def test_returns_none_when_index_file_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("src.retrieval.vectorstore.FAISS_PATH", str(tmp_path / "nonexistent"))

    result = VectorStoreFactory.load(embeddings=object())

    assert result is None


def test_returns_none_for_a_directory_missing_the_index_file(tmp_path, monkeypatch):
    # Directory exists (e.g. an empty mounted volume) but has no
    # index.faiss in it yet -- still "no index", not an error.
    (tmp_path / "some_other_file.txt").write_text("not an index")
    monkeypatch.setattr("src.retrieval.vectorstore.FAISS_PATH", str(tmp_path))

    result = VectorStoreFactory.load(embeddings=object())

    assert result is None
