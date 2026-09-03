"""Evaluation harness for the reasoning layer.

This module currently holds the benchmark question set loader. Part 3 of Session 5
adds the deterministic metric functions alongside it.

The benchmark lives in ``tests/benchmark/questions.yaml``; see the header of that
file for the annotation procedure and the meaning of the relevance grades.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

DEFAULT_BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "tests" / "benchmark" / "questions.yaml"

REASONING_TYPES = ("topic", "function", "mechanism")
CONFIDENCE_LABELS = ("high", "moderate", "low", "none")
RELEVANCE_GRADES = (1, 2)


@dataclass(frozen=True)
class BenchmarkQuestion:
    """One hand-annotated benchmark question over the frozen 64-abstract corpus.

    Attributes:
        id: Stable identifier, e.g. ``"q01"``.
        question: The query string, passed verbatim to ``reasoning.answer_question``.
        reasoning_type: Expected classification. For the multi-clause item this is the
            leading clause's type; see that question's notes.
        reference_answer: Answer written from the abstracts, used by the Part 5 judge.
            For out-of-distribution questions this states that abstention is expected.
        relevance: PMID to grade, for screened-nonzero documents only. Grade ``2`` means
            the abstract directly supports a claim an answer should make; grade ``1``
            means topically relevant background. Grade ``0`` documents are omitted.
        expected_confidence: Accepted set of ``confidence`` labels, not a single label:
            annotators genuinely disagree on moderate-vs-low.
        expects_fallback: True for out-of-distribution questions, which must trigger the
            deterministic fallback and have an empty relevance map.
        expected_failure: True for the pre-declared multi-clause item, which is excluded
            from headline metrics and reported separately.
        notes: Annotation provenance, measured distances, and known caveats.
    """

    id: str
    question: str
    reasoning_type: Literal["topic", "function", "mechanism"]
    reference_answer: str
    relevance: dict[str, int]
    expected_confidence: frozenset[str]
    expects_fallback: bool
    expected_failure: bool
    notes: str = ""

    @property
    def relevant_pmids(self) -> frozenset[str]:
        """The relevant set G: every PMID graded 1 or 2."""
        return frozenset(self.relevance)

    @property
    def supporting_pmids(self) -> frozenset[str]:
        """The citation ground truth S: every PMID graded 2."""
        return frozenset(pmid for pmid, grade in self.relevance.items() if grade == 2)


def load_benchmark(path: str | Path = DEFAULT_BENCHMARK_PATH) -> list[BenchmarkQuestion]:
    """Load and structurally validate the benchmark question set.

    Args:
        path: Path to the YAML question set. Defaults to the committed benchmark.

    Returns:
        The questions in file order.

    Raises:
        ValueError: If the file is not a list of question mappings, if a question is
            missing a required key or carries an unknown one, or if a field has the
            wrong type. Semantic checks on the question mix live in
            ``tests/test_benchmark_schema.py``; this function only guarantees that
            every entry can be trusted as a ``BenchmarkQuestion``.
    """
    with open(path) as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of questions, got {type(raw).__name__}")

    required = {"id", "question", "reasoning_type", "reference_answer", "relevance",
                "expected_confidence", "expects_fallback", "expected_failure"}
    allowed = required | {"notes"}

    questions = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: question at index {index} is not a mapping")

        where = entry.get("id", f"index {index}")
        missing = required - entry.keys()
        if missing:
            raise ValueError(f"{path}: question {where} is missing keys {sorted(missing)}")
        unknown = entry.keys() - allowed
        if unknown:
            raise ValueError(f"{path}: question {where} has unknown keys {sorted(unknown)}")

        relevance = entry["relevance"] or {}
        if not isinstance(relevance, dict):
            raise ValueError(f"{path}: question {where} has a non-mapping relevance field")
        if not all(isinstance(pmid, str) for pmid in relevance):
            raise ValueError(
                f"{path}: question {where} has non-string PMID keys; quote them in the YAML"
            )

        confidence = entry["expected_confidence"]
        if not isinstance(confidence, list) or not confidence:
            raise ValueError(f"{path}: question {where} needs a non-empty expected_confidence list")

        for flag in ("expects_fallback", "expected_failure"):
            if not isinstance(entry[flag], bool):
                raise ValueError(f"{path}: question {where} has a non-boolean {flag}")

        questions.append(BenchmarkQuestion(
            id=entry["id"],
            question=entry["question"],
            reasoning_type=entry["reasoning_type"],
            reference_answer=entry["reference_answer"].strip(),
            relevance=dict(relevance),
            expected_confidence=frozenset(confidence),
            expects_fallback=entry["expects_fallback"],
            expected_failure=entry["expected_failure"],
            notes=entry.get("notes", "").strip(),
        ))

    return questions
