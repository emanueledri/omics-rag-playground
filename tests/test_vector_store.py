"""Tests for the vector store module."""

import chromadb
import numpy as np
import pytest

from omics_rag_playground.vector_store import (
    COSINE_CONFIGURATION,
    DEFAULT_DB_PATH,
    query_collection,
)


def test_default_db_path_is_cwd_independent():
    """The default path must resolve to the repo data dir from any CWD."""
    assert DEFAULT_DB_PATH.is_absolute()
    assert DEFAULT_DB_PATH.parts[-3:] == ("data", "processed", "chroma_db")


def test_query_collection_raises_on_empty_collection():
    """An empty collection must fail loudly instead of returning no results."""
    collection = chromadb.EphemeralClient().create_collection(
        name="empty_collection",
        configuration=COSINE_CONFIGURATION,
    )

    def unused_embed_fn(texts):
        raise AssertionError("embedding should not be attempted on an empty collection")

    with pytest.raises(ValueError, match="empty_collection"):
        query_collection(collection, "any query", embed_fn=unused_embed_fn)


def test_query_collection_returns_cosine_distances():
    """Distances from a cosine collection are 1 - cos, ascending."""
    collection = chromadb.EphemeralClient().create_collection(
        name="cosine_collection",
        configuration=COSINE_CONFIGURATION,
    )
    identical = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    orthogonal = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    collection.upsert(
        ids=["same", "orthogonal"],
        documents=["same", "orthogonal"],
        embeddings=np.vstack([identical, orthogonal]),
    )

    results = query_collection(collection, "query", embed_fn=lambda texts: identical[None, :])

    assert [r[0] for r in results] == ["same", "orthogonal"]
    assert results[0][3] == pytest.approx(0.0, abs=1e-6)
    assert results[1][3] == pytest.approx(1.0, abs=1e-6)
