from omics_rag_playground.annotation import map_ensembl_to_symbol


def test_known_gene_versioned():
    """CRISPLD2 is well-known and should map cleanly even with version suffix."""
    result = map_ensembl_to_symbol(["ENSG00000103196.10"])
    assert result.iloc[0] == "CRISPLD2"


def test_known_gene_unversioned():
    """Same gene without version suffix should also work."""
    result = map_ensembl_to_symbol(["ENSG00000103196"])
    assert result.iloc[0] == "CRISPLD2"


def test_index_preserves_input_format():
    """Result index must match input format exactly."""
    versioned = "ENSG00000103196.10"
    result = map_ensembl_to_symbol([versioned])
    assert versioned in result.index