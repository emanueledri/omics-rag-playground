# Design notes

## Session 1: warm-up DE on airway

**What worked**
- pyDESeq2 single-factor design ran clean on airway
- LFC shrinkage stabilized the volcano plot tail nicely
- mygene mapping covered ~85% of genes

**Open questions**
- Would it be useful to find a more efficient mapping method for big datasets?
- Why `refit_cooks=True`? Read up on Cook's distance for outlier handling.

**Next session plan**
- Move to GSE50760 (colorectal cancer, 3 conditions)
- Multi-factor design `~patient + condition`

## Session 2: liver contamination in GSE50760 met-vs-tumor

### Findings

The metastasis-vs-tumor contrast in this dataset is dominated by liver 
tissue identity (LFC ~9 for hundreds of hepatocyte transcripts, persisting 
after filtering ~150 known liver markers). Lesson: paired primary/metastasis 
bulk RNA-seq is fundamentally limited for metastasis-biology questions in 
this study design. To investigate metastatic-specific signaling, would need 
either deconvolution methods or single-cell approaches.

Reference: this is a known limitation in the field but not always 
prominently flagged in tutorial use of GSE50760. Worth a writeup as a 
short blog post or as part of the project README's "lessons learned".

### Takeaways

**Pipeline now solid on real cancer data.** Full DE workflow on GSE50760 
end-to-end: recount3 acquisition with coverage→counts conversion, single-
factor + multi-factor designs in parallel, two contrasts, pathway enrichment.
Biologically coherent results recapitulating the canonical CRC molecular 
phenotype (EMT, proliferation, microenvironment activation, dedifferentiation).

**Multi-factor design materially changes which biology is visible.** 
`~patient + condition` recovers +23.5% DE genes vs `~condition`. The newly 
visible signal is concentrated in the *downregulated* arm — the simple 
model masked the loss-of-colonic-identity signature (BEST4, OTOP2, CA7) 
because their inter-donor variability was being treated as noise. Patient 
blocking is not a refinement, it's a different lens on the data.

**Cook's outlier count as a diagnostic.** The `Replacing N outlier genes` 
line in DESeq2 output is informative beyond the genes themselves: 1100 
under `~condition` vs 0 under `~patient + condition` was the first 
quantitative signal that the simple model was misattributing variance.

**Annotation module proven useful.** `map_ensembl_to_symbol` with on-disk 
cache was reused 4 times across the GSE50760 notebook (single-factor 
TN/MT, multi-factor TN, plus all enrichment gene lists). The cache made 
the 2nd-4th calls effectively free. Justifies the early decision to 
promote it to `src/`.

### Open questions

- **Multi-factor LFC shrinkage**: not attempted. Same overflow concerns 
  as single-factor, but worth a future check — the patient-controlled 
  fit might be better-conditioned for the prior fitting.
- **Down-pathway interpretation**: the multi-factor downregulated 
  enrichment looks more sharply differentiation/metabolism-focused but 
  I have not done a formal pathway-level diff (e.g. set difference of 
  hallmarks at FDR<0.05 between SF and MF). Could be a 30-min follow-up.
- **Heatmap of top DE genes**: produced for airway warm-up, not for 
  GSE50760. Could add a heatmap of top 30 DE genes from the multi-
  factor model with samples annotated by patient + condition — would 
  visually demonstrate the patient-blocking effect. Low priority.

## Session 3: RAG retrieval + embedding scaffold

### Retrieval primitive design
[breve riassunto delle decisioni: Biopython, dataclass, cache by PMID, 
fixture-based testing for parser branches]

### Notable finding from notebook 02
Two of the top-5 up-regulated DE genes (SERPINB7, DNMT3L) returned 
zero CRC abstracts under a Title/Abstract + MeSH Major Topic query.
Independent of retrieval quality, this is a real signal: top-LFC 
genes that are absent from CRC literature are candidate "novel" 
hits and arguably the most interesting cases for the downstream 
reasoning layer to flag explicitly.

### embedding model selection

- Embeddings are L2-normalized at encode time (`normalize_embeddings=True`):
  cosine similarity reduces to dot product downstream, and ChromaDB's
  default L2 distance becomes rank-equivalent to cosine.

Chose NeuML/pubmedbert-base-embeddings over alternatives. Rationale:
- Sentence-transformers compatible (drop-in via SentenceTransformer 
  class), 110M params, 768-dim, Apache 2.0, ~600 docs/sec on CPU.
- Trained directly on PubMed title-abstract pairs (proper sentence-
  level contrastive training, unlike vanilla PubMedBERT/BioBERT 
  which are MLM-only and produce poor retrieval embeddings).
- BMRetriever-410M would offer ~+8% on biomedical BEIR but requires 
  custom loading + LLM-style pooling — deferred as upgrade path.
- General-purpose alternatives (all-mpnet-base-v2, BGE) trail 
  biomedical fine-tunes by 5-15% on BEIR biomedical subsets.

Sanity check confirmed: cosine(BEST4, OTOP2) > cosine(BEST4, IL-2 
control), with a margin of 0.48. 

### MeSH enrichment ablation

Tested whether appending MeSH Major Topics to the embedded text 
("title + abstract + 'MeSH: t1; t2; ...'") improves retrieval over 
title + abstract alone. Compared on 3 query types (topic-level, 
gene+function, mechanism-specific) with the same abstract corpus.

A/B compared two embedding strategies on the same abstract corpus 
and three demo queries: title + abstract (baseline) vs title + 
abstract + "MeSH: t1; t2; ...".

Result: null effect. Top-5 retrieved PMIDs identical or nearly so, 
distance shifts in the 0.001-0.02 range, occasional rank swaps 
that don't change the substantive interpretation.

Decision: drop MeSH appending for Stage 3. Keep title + abstract.

Why null: (a) PubMedBERT pre-training already encodes MeSH ontology, 
(b) the retrieval query enforces "Colorectal Neoplasms" Major Topic 
on every abstract, making it a constant feature, (c) abstract text 
already contains the discriminative vocabulary.

This is a useful negative result: a portfolio-level ablation study 
that motivates a simpler chunking strategy and saves token budget 
in downstream Stage 3 reasoning.

### Deduplication before vector store ingest

Some PubMed records appear multiple times in our flat list because they 
match queries for multiple genes (e.g. a single-cell colon paper hits 
both BEST4 and OTOP2 queries). We deduplicate by PMID before ingest, 
collapsing the gene-of-origin into a "; "-separated string. This ensures 
each abstract appears once in retrieval results, at the cost of losing 
single-gene filterability — acceptable since gene-of-origin is recoverable 
from the original flat lists when needed.

## Session 4: reasoning layer

Wired the Stage 2 retrieval scaffold to an LLM. The reasoning layer takes a user question, retrieves k abstracts from the Stage 2 ChromaDB collection, and returns a grounded answer with explicit citations, a confidence level, and a reasoning_type classification.

### LLM provider

Chose **Claude Haiku 4.5** via `langchain-anthropic`. Three reasons:
- Coherent with the development context (project built in chat with Claude).
- Strong instruction-following on grounding rules and structured output, which matters for citation-only-from-abstracts.
- Cost is negligible (≈ $0.005 per call on a 5-abstract prompt); the entire Stage 3 development burnt under $0.10.

OpenAI and local Llama 3.1 via Ollama considered as alternatives. Both viable as future swaps via `model` parameter of `answer_question`. Not implemented because portability proof is not the goal of Stage 3.

### Output schema

Internal Pydantic `GroundedAnswer` with four fields: `answer`, `citations: list[str]`, `confidence: Literal["high","moderate","low","none"]`, `reasoning_type: Literal["topic","function","mechanism"]`. Used as the schema argument to `with_structured_output`, which under the hood uses Anthropic's native tool-use for reliable structured output.

`GroundedAnswer` is an implementation detail. The module's public interface is the existing `ReasoningResult` dataclass, into which `GroundedAnswer` fields are copied. This keeps the external API stable between Block 1 (where citations/confidence/reasoning_type were placeholders) and Block 2.

A potential fifth field `caveats: str | None` for contradictory-evidence notes was discussed and parked for Stage 5 — the evaluation harness will surface whether it is genuinely needed.

### Prompt design

The system prompt is structured in four explicit sections: grounding rule, reasoning type definitions, confidence level definitions, citation rule. Zero-shot, no few-shot examples — Haiku 4.5 follows instructions reliably enough at this complexity that few-shot was not necessary.

Citation grounding is **soft**: the `citations` list aggregates all PMIDs supporting the answer, with no inline `[PMID:12345]` tagging per claim. The hard version was rejected as more fragile for downstream parsing and less readable. Stage 5 evaluation will tell us whether it is sufficient.

A one-line nudge — "Classify based on what the question asks for, not what the abstracts contain" — was added to the reasoning_type section after observing that the model classified topic-level queries as function based on the content of retrieved abstracts. This addressed Q1 but introduced borderline cases (see Reasoning_type fuzziness below).

### Reasoning_type classification is approximate

The reasoning_type field is the least load-bearing of the four — it does not gate downstream decisions, unlike `confidence` and `citations`. It is observably imperfect on multi-clause queries: an earlier formulation of Q2 ("Is BEST4 a marker of normal colonic differentiation? What is its role in CRC?") was consistently classified as `topic` (the first clause dominated), even after the prompt nudge above. Q2 was rewritten to be unambiguously function.

A production system would either decompose multi-clause questions before classification or treat reasoning_type as a probability distribution over the three classes rather than a single label. For a portfolio system, the observation is documented as a known limitation.

### Test strategy

Two-layer approach mirroring `tests/test_retrieval.py`:
- Offline tests with an in-memory ChromaDB collection (3 toy abstracts) and a stubbed `_get_llm` returning a hand-crafted `GroundedAnswer`. No network, no API key, always-on.
- A network-marked smoke test that hits the real Anthropic API. Opt-in via `pytest -m network`.

The `lru_cache` getter pattern in `_get_llm` makes monkeypatching trivial — verified empirically that the same pattern used in `embeddings._get_model` works for the LLM.

### Literature-sparse fallback

`answer_question` short-circuits the LLM when retrieval is structurally weak. Two trigger conditions:
- Empty retrieval (`len(retrieved) == 0`): defensive — never observed in practice because ChromaDB always returns `n_results` results sorted by distance.
- All retrieved distances above a threshold T: the active trigger in practice.

The decision criterion is *all top-k distances above T*, not *top-1 above T*. This makes the trigger conservative: a single relevant abstract is enough to pass through to the LLM.

When triggered, the fallback returns a deterministic "no relevant literature found" message with `confidence="none"`, `citations=[]`, `reasoning_type=None`. No API call is made — verified by a dedicated unit test (`test_fallback_short_circuits_llm`) in which the stub LLM raises if invoked.

### Threshold calibration

T = 1.10 chosen as the baseline based on the Block 3 demo queries on the Stage 2 ChromaDB collection (40 unique PMIDs from gene-symbol queries on the top DE genes of Stage 1):

| Query | Top-5 cosine distance range | Should trigger | Triggers? |
|---|---|---|---|
| Q1 — EMT in CRC (topic) | 1.109 – 1.215 | yes | yes |
| Q2 — BEST4 role in CRC (function) | 1.094 – 1.287 | no | no |
| Q3 — WNT signaling in CRC (mechanism) | 0.860 – 1.201 | no | no |
| Q_OOD — HIV reverse transcriptase | (all > 1.10) | yes | yes |

The chosen T = 1.10 is **empirically tight**: Q1's top-1 distance is 1.109, only 0.015 above threshold. The value is appropriate as a baseline for testing the fallback mechanism on a small (N=3) calibration set, but should be re-tuned on a larger evaluation harness in Stage 5 before being trusted in production. T is exposed as a parameter of `answer_question` to make per-call overrides easy.

### Decisions parked for Stage 5

- `caveats` field on `GroundedAnswer` for contradictory-evidence annotation
- Larger evaluation harness for T calibration
- Hard citation grounding (inline `[PMID:12345]` per claim) if soft proves insufficient
- Multi-clause query decomposition or probabilistic reasoning_type
- Mechanism queries that reference absent context (Q3 of the demo) — currently silently re-interpreted by the model, not flagged