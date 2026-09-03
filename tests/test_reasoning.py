"""Tests for the reasoning module."""

from __future__ import annotations

import chromadb
import pytest
from dotenv import load_dotenv
from langchain_core.messages import AIMessage

load_dotenv()

from omics_rag_playground import reasoning
from omics_rag_playground.embeddings import embed_abstracts
from omics_rag_playground.reasoning import GroundedAnswer, _should_trigger_fallback


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def populated_collection():
    """Build an in-memory ChromaDB collection with 3 toy abstracts.

    The abstracts are short and gene-themed so the embedding model produces
    meaningful (if low-quality) similarities. Sufficient for structural tests.
    """
    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        name="test_pubmed_abstracts",
        metadata={"hnsw:space": "cosine"},
    )

    docs = [
        {
            "pmid": "10000001",
            "title": "BEST4 marker of colonic differentiation",
            "abstract": (
                "BEST4 is a calcium-activated chloride channel expressed in "
                "a rare population of colonic epithelial cells. Its expression "
                "marks differentiated absorptive enterocytes in normal colon."
            ),
        },
        {
            "pmid": "10000002",
            "title": "OTOP2 in colorectal cancer",
            "abstract": (
                "OTOP2 encodes a proton-selective ion channel and is "
                "downregulated in colorectal tumors compared to matched normal "
                "mucosa. Loss of OTOP2 is a marker of dedifferentiation."
            ),
        },
        {
            "pmid": "10000003",
            "title": "Carbonic anhydrase 7 expression in colon",
            "abstract": (
                "Carbonic anhydrase 7 (CA7) is highly expressed in normal "
                "colonic epithelium and significantly reduced in colorectal "
                "cancer tissue, suggesting a role in tumor suppression."
            ),
        },
    ]

    texts = [f"{d['title']}\n\n{d['abstract']}" for d in docs]
    embeddings = embed_abstracts(texts).tolist()

    collection.add(
        ids=[d["pmid"] for d in docs],
        documents=texts,
        embeddings=embeddings,
        metadatas=[{"pmid": d["pmid"], "title": d["title"]} for d in docs],
    )

    yield collection
    client.delete_collection("test_pubmed_abstracts")


# --- Offline structural tests -----------------------------------------------


def test_answer_question_end_to_end(populated_collection, monkeypatch):
    """Full pipeline runs with a stubbed LLM and a local collection."""

    class StubLLM:
        def with_structured_output(self, schema):
            return self  # so .invoke returns GroundedAnswer below
        def invoke(self, messages):
            return GroundedAnswer(
                answer="stubbed answer",
                citations=["10000001"],
                confidence="moderate",
                reasoning_type="function",
            )

    monkeypatch.setattr(reasoning, "_get_llm", lambda model=None: StubLLM())

    result = reasoning.answer_question(
        query="What is BEST4 in colonic epithelium?",
        collection=populated_collection,
        n_retrieved=3,
    )

    assert result.answer == "stubbed answer"
    assert len(result.retrieved_pmids) == 3
    assert len(result.retrieved_distances) == 3
    assert all(isinstance(p, str) for p in result.retrieved_pmids)
    assert all(isinstance(d, float) for d in result.retrieved_distances)
    assert result.citations == ["10000001"]
    assert result.confidence == "moderate"
    assert result.reasoning_type == "function"


def test_retrieved_pmids_are_from_collection(populated_collection, monkeypatch):
    """Retrieved PMIDs must be a subset of what was ingested."""

    class StubLLM:
        def with_structured_output(self, schema):
            return self
        def invoke(self, messages):
            return GroundedAnswer(
                answer="stubbed answer",
                citations=["10000001"],
                confidence="moderate",
                reasoning_type="function",
            )

    monkeypatch.setattr(reasoning, "_get_llm", lambda model=None: StubLLM())

    result = reasoning.answer_question(
        query="colonic differentiation",
        collection=populated_collection,
        n_retrieved=2,
    )

    expected_pmids = {"10000001", "10000002", "10000003"}
    assert set(result.retrieved_pmids).issubset(expected_pmids)
    assert len(result.retrieved_pmids) == 2


# --- Live smoke test --------------------------------------------------------


@pytest.mark.network
def test_answer_question_live_smoke(populated_collection):
    """End-to-end call against the real Anthropic API.

    Requires ANTHROPIC_API_KEY in the environment. Skipped by default in CI;
    run explicitly with `pytest -m network`.
    """
    result = reasoning.answer_question(
        query="What is BEST4 in colonic epithelium?",
        collection=populated_collection,
        n_retrieved=3,
    )

    # print(f"\n{result}")

    assert isinstance(result.answer, str)
    assert len(result.answer) > 0
    assert len(result.retrieved_pmids) == 3

# --- Fallback trigger tests -------------------------------------------------
# Thresholds and distances are on the cosine scale (``1 - cos``), which is what
# both the fixture collection and the rebuilt production store report.


def test_fallback_triggers_on_empty_retrieval():
    """Empty retrieval should trigger the fallback regardless of threshold."""
    assert _should_trigger_fallback([], distance_threshold=0.55) is True


def test_fallback_triggers_when_all_distances_above_threshold():
    """All distances above threshold should trigger the fallback."""
    distances = [0.555, 0.575, 0.60]
    assert _should_trigger_fallback(distances, distance_threshold=0.55) is True


def test_fallback_does_not_trigger_when_any_distance_below_threshold():
    """At least one distance below threshold should bypass the fallback."""
    distances = [0.545, 0.575, 0.60]
    assert _should_trigger_fallback(distances, distance_threshold=0.55) is False


def test_fallback_short_circuits_llm(populated_collection, monkeypatch):
    """When fallback triggers, the LLM should not be called."""
    
    class ExplodingStubLLM:
        def with_structured_output(self, schema):
            return self
        def invoke(self, messages):
            raise AssertionError("LLM should not be called when fallback triggers")
    
    monkeypatch.setattr(reasoning, "_get_llm", lambda model=None: ExplodingStubLLM())
    
    # Threshold = 0.0 forces all distances above threshold → fallback triggers.
    result = reasoning.answer_question(
        query="anything",
        collection=populated_collection,
        n_retrieved=3,
        distance_threshold=0.0,
    )
    
    assert result.confidence == "none"
    assert result.citations == []
    assert result.reasoning_type is None
    assert "No relevant literature" in result.answer