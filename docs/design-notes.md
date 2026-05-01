# Design notes

## Session 1 (2026-04-25)

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