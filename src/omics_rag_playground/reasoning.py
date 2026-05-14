"""Reasoning module for the omics RAG playground."""

from dataclasses import dataclass
from functools import lru_cache
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field
from typing import Literal
import os

from omics_rag_playground.vector_store import query_collection
from omics_rag_playground.embeddings import embed_abstracts


@dataclass(frozen=True)
class ReasoningResult:
    """Class to store the results of a reasoning process."""
    answer: str
    retrieved_pmids: list[str]
    retrieved_distances: list[float]
    citations: list[str] | None = None
    confidence: Literal['high', 'moderate', 'low', 'none'] | None = None
    reasoning_type: Literal['topic', 'function', 'mechanism'] | None = None

_SYSTEM_PROMPT = """You are a biomedical research assistant for gene-disease \
question answering grounded in PubMed abstracts.

Grounding rule:
Answer the user's question using only the provided abstracts. \
Do not use external knowledge. Do not speculate beyond what the abstracts state.

Reasoning type:
Classify the question by what is being asked, not by the content of the abstracts:
- topic: questions asking *which* genes/papers/conditions are associated with a phenomenon ("Which genes are involved in X?")
- function: questions asking *what* a specific gene does ("What is the role of gene X?")
- mechanism: questions asking *how* something happens, requiring causal chains

Confidence levels:
- high: multiple abstracts directly answer the question with consistent evidence
- moderate: abstracts answer the question partially, or evidence is consistent but limited (e.g. single abstract)
- low: abstracts only tangentially address the question, requiring inference
- none: abstracts do not contain information to answer the question

Citation rule:
The citations field must contain all and only the PMIDs of the abstracts you \
used to support your answer. No PMIDs of abstracts you did not use. No claims \
without a corresponding PMID in citations.
"""

_USER_TEMPLATE = """<abstracts>
{formatted_abstracts}
</abstracts>

Question: {query}"""

_FALLBACK_MESSAGE = (
    "No relevant literature was found in the corpus for this query. "
    "Either the retrieval returned no abstracts, or all retrieved abstracts "
    "are too dissimilar from the query to provide reliable grounding."
)

class GroundedAnswer(BaseModel):
    """Internal schema for the LLM structured output."""
    
    answer: str = Field(description="Answer to the user's question, grounded in the provided abstracts.")
    citations: list[str] = Field(description="PMIDs of abstracts that support the answer. Empty list if no abstract supports the answer.")
    confidence: Literal["high", "moderate", "low", "none"] = Field(description="Confidence level based on the strength of evidence in the cited abstracts.")
    reasoning_type: Literal["topic", "function", "mechanism"] = Field(description="Classification of the question type.")

@lru_cache(maxsize=4)
def _get_llm(model: str = "claude-haiku-4-5-20251001") -> ChatAnthropic:
    """Get the LLM instance."""
    return ChatAnthropic(model_name=model, api_key=os.getenv("ANTHROPIC_API_KEY"))

def _format_abstracts(records: list[dict]) -> str:
    """Format the abstracts for the LLM XML-like input."""
    formatted_abstracts = []
    for record in records:
        pmid = record.get("pmid", "unknown")
        title = record.get("title", "No title")
        abstract = record.get("abstract", "No abstract")
        formatted_abstracts.append(f"<abstract><pmid>{pmid}</pmid><title>{title}</title><content>{abstract}</content></abstract>")
    return "\n".join(formatted_abstracts)

def answer_question(query: str, collection, n_retrieved: int = 5, 
                    distance_threshold: float = 1.15, model: str = "claude-haiku-4-5-20251001") -> ReasoningResult:
    """Answer a question using the retrieved abstracts.

    Parameters
    ----------
    query : str
        User question.
    collection
        ChromaDB collection of biomedical abstracts.
    n_retrieved : int
        Number of abstracts to retrieve from the collection.
    model : str
        Anthropic model name.
    distance_threshold : float
        Cosine distance threshold for the literature-sparse fallback.
        If all retrieved abstracts have distance above this, the LLM call
        is skipped and a "no relevant literature" message is returned.
        Baseline 1.10 calibrated on the Stage 2 / Block 3 demo queries.
    """
  
    retrieved = query_collection(collection, query, embed_fn=embed_abstracts, n_results=n_retrieved)
    retrieved_pmids = [r[0] for r in retrieved]
    retrieved_distances = [r[3] for r in retrieved]

    # construct the prompt with the XML block
    formatted_abstracts = _format_abstracts([{"pmid": pmid, **r[2], "abstract": r[1]} for pmid, r in zip(retrieved_pmids, retrieved)])
    text_prompt = _USER_TEMPLATE.format(formatted_abstracts=formatted_abstracts, query=query)

    # Check if we should trigger the fallback before calling the LLM
    if _should_trigger_fallback(retrieved_distances, distance_threshold):
        return ReasoningResult(
            answer=_FALLBACK_MESSAGE,
            retrieved_pmids=retrieved_pmids,
            retrieved_distances=retrieved_distances,
            citations=[],
            confidence="none",
            reasoning_type=None,
        )

    llm = _get_llm(model)
    structured_llm = llm.with_structured_output(GroundedAnswer)

    grounded_response = structured_llm.invoke([
        ("system", _SYSTEM_PROMPT),
        ("user", text_prompt),
    ])

    return ReasoningResult(
        answer=grounded_response.answer,
        retrieved_pmids=retrieved_pmids,
        retrieved_distances=retrieved_distances,
        citations=grounded_response.citations,
        confidence=grounded_response.confidence,
        reasoning_type=grounded_response.reasoning_type,
    )


def _should_trigger_fallback(retrieved_distances: list[float], distance_threshold: float) -> bool:
    """Decide whether to short-circuit the LLM call.
    
    Two conditions trigger the fallback:
    - Empty retrieval (no abstracts returned at all)
    - All retrieved abstracts have cosine distance above threshold,
      indicating the corpus does not contain relevant literature.
    
    Parameters
    ----------
    retrieved_distances : list[float]
        Cosine distances of retrieved abstracts, ordered ascending.
    distance_threshold : float
        Maximum cosine distance considered relevant.
    
    Returns
    -------
    bool
        True if the fallback should be triggered.
    """
    if len(retrieved_distances) == 0 or all(d > distance_threshold for d in retrieved_distances):
        return True
    return False

