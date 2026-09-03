"""Schema and consistency checks for the benchmark question set.

These are structural assertions on a committed data artefact, so they run offline and
carry no `network` marker. They exist so that an edit to questions.yaml that would
silently make a metric undefined -- an out-of-distribution question with a non-empty
relevant set, an in-corpus question with no grade-2 abstract, a PMID that is not in the
frozen corpus -- fails here instead of surfacing as a plausible-looking number in
notebook 04.
"""

import json
from pathlib import Path

import pytest

from omics_rag_playground.evaluation import (
    CONFIDENCE_LABELS,
    REASONING_TYPES,
    RELEVANCE_GRADES,
    load_benchmark,
)

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
EXPECTED_TOTAL = 20
EXPECTED_PER_TYPE = 5
EXPECTED_OOD = 4
EXPECTED_FAILURES = 1


@pytest.fixture(scope="module")
def questions():
    return load_benchmark(BENCHMARK_DIR / "questions.yaml")


@pytest.fixture(scope="module")
def corpus_pmids():
    manifest = json.loads((BENCHMARK_DIR / "corpus_manifest.json").read_text())
    return {record["pmid"] for record in manifest["records"]}


@pytest.fixture(scope="module")
def core(questions):
    """The 15 in-corpus questions that carry the headline metrics."""
    return [q for q in questions if not q.expects_fallback and not q.expected_failure]


def test_question_count_and_unique_ids(questions):
    assert len(questions) == EXPECTED_TOTAL
    ids = [q.id for q in questions]
    assert len(set(ids)) == len(ids), "duplicate question ids"


def test_groups_partition_the_set(questions, core):
    ood = [q for q in questions if q.expects_fallback]
    failures = [q for q in questions if q.expected_failure]

    assert len(ood) == EXPECTED_OOD
    assert len(failures) == EXPECTED_FAILURES
    # No question may be both, or the three groups would not sum to the total.
    assert len(core) + len(ood) + len(failures) == EXPECTED_TOTAL


def test_core_reasoning_type_mix(core):
    counts = {reasoning_type: 0 for reasoning_type in REASONING_TYPES}
    for question in core:
        counts[question.reasoning_type] += 1
    assert counts == {reasoning_type: EXPECTED_PER_TYPE for reasoning_type in REASONING_TYPES}


def test_reasoning_types_are_known(questions):
    for question in questions:
        assert question.reasoning_type in REASONING_TYPES, question.id


def test_confidence_labels_are_known(questions):
    for question in questions:
        assert question.expected_confidence <= set(CONFIDENCE_LABELS), question.id


def test_relevance_grades_are_known(questions):
    for question in questions:
        for pmid, grade in question.relevance.items():
            assert grade in RELEVANCE_GRADES, f"{question.id}/{pmid} graded {grade}"


def test_relevance_pmids_are_in_the_frozen_corpus(questions, corpus_pmids):
    for question in questions:
        unknown = question.relevant_pmids - corpus_pmids
        assert not unknown, f"{question.id} grades PMIDs not in the manifest: {sorted(unknown)}"


def test_ood_questions_have_empty_ground_truth(questions):
    for question in questions:
        if not question.expects_fallback:
            continue
        assert question.relevance == {}, f"{question.id} expects fallback but grades documents"
        assert question.expected_confidence == {"none"}, question.id


def test_answerable_questions_have_a_supporting_abstract(questions):
    """Grade-2 documents are the citation ground truth S; without one, citation
    precision and recall are undefined for that question."""
    for question in questions:
        if question.expects_fallback:
            continue
        assert question.supporting_pmids, f"{question.id} has no grade-2 PMID"
        assert "none" not in question.expected_confidence, (
            f"{question.id} is answerable but accepts confidence 'none'"
        )


def test_reference_answers_are_present(questions):
    for question in questions:
        assert question.reference_answer, f"{question.id} has an empty reference_answer"


def test_supporting_set_is_a_subset_of_the_relevant_set(questions):
    for question in questions:
        assert question.supporting_pmids <= question.relevant_pmids, question.id


def test_notes_record_annotation_provenance(questions):
    for question in questions:
        assert question.notes, f"{question.id} has no annotation notes"


def test_loader_rejects_a_missing_key(tmp_path):
    path = tmp_path / "questions.yaml"
    path.write_text('- id: q01\n  question: "why?"\n')
    with pytest.raises(ValueError, match="missing keys"):
        load_benchmark(path)


def test_loader_rejects_unquoted_numeric_pmids(tmp_path):
    """PMIDs are strings everywhere downstream. An unquoted YAML key parses as an int
    and would silently never match a retrieved PMID, scoring every metric as zero."""
    path = tmp_path / "questions.yaml"
    path.write_text(
        "- id: q01\n"
        '  question: "why?"\n'
        "  reasoning_type: function\n"
        '  reference_answer: "because"\n'
        "  relevance:\n"
        "    39699952: 2\n"
        "  expected_confidence: [high]\n"
        "  expects_fallback: false\n"
        "  expected_failure: false\n"
    )
    with pytest.raises(ValueError, match="non-string PMID keys"):
        load_benchmark(path)
