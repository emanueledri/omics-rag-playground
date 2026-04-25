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