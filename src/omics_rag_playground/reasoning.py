"""Reasoning module for the omics RAG playground."""

from dataclasses import dataclass
from functools import lru_cache
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
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

_SYSTEM_PROMPT = "You are a biomedical research assistant. Answer the user's question using only the abstracts provided. Be concise."

@lru_cache(maxsize=4)
def _get_llm(model: str = "claude-haiku-4-5-20251001") -> ChatAnthropic:
    """Get the LLM instance."""
    return ChatAnthropic(model_name=model, api_key=os.getenv("ANTHROPIC_API_KEY"))

def _format_abstracts(records) -> str:
    """Format the abstracts for the LLM XML-like input."""
    formatted_abstracts = []
    for record in records:
        pmid = record.get("pmid", "unknown")
        title = record.get("title", "No title")
        abstract = record.get("abstract", "No abstract")
        formatted_abstracts.append(f"<abstracts'><abstract><pmid>{pmid}</pmid><title>{title}</title><content>{abstract}</content></abstract></abstracts>")
    return formatted_abstracts

def answer_question(query: str, collection, n_retrieved: int = 5, model: str = "claude-haiku-4-5-20251001") -> ReasoningResult:
    """Answer a question using the retrieved abstracts."""
    llm = _get_llm(model)
    retrieved = query_collection(collection, query, embed_fn=embed_abstracts, n_results=n_retrieved)
    retrieved_pmids = [r[0] for r in retrieved]
    retrieved_distances = [r[3] for r in retrieved]

    # construct the prompt with the XML block
    formatted_abstracts = _format_abstracts([{**r[2], "abstract": r[1]} for r in retrieved])
    text_prompt = f"""<question>{query}</question>{''.join(formatted_abstracts)}"""

    # wrap prompt in BaseMessage format for langchain
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=text_prompt)]
    response = llm.invoke(messages)

    return ReasoningResult(
        answer=response.content,
        retrieved_pmids=retrieved_pmids,
        retrieved_distances=retrieved_distances,
    )