"""Gene annotation utilities.

This module wraps external annotation services (mygene.info) with
caching and ID normalization, providing clean primitives for mapping
gene identifiers across naming conventions.
"""

from __future__ import annotations

import json
from pathlib import Path

import mygene
import pandas as pd


def _strip_version(ensembl_id: str) -> str:
    """Strip the version suffix from a versioned Ensembl ID.
    
    e.g. 'ENSG00000122641.10' -> 'ENSG00000122641'
    """
    return ensembl_id.split(".")[0]


def map_ensembl_to_symbol(
    ensembl_ids: list[str] | pd.Index,
    species: str = "human",
    cache_path: str | Path | None = None,
) -> pd.Series:
    """Map Ensembl gene IDs to HGNC symbols via mygene.info.

    Handles both versioned (ENSG00000122641.10) and unversioned
    (ENSG00000122641) IDs transparently.

    Parameters
    ----------
    ensembl_ids
        Iterable of Ensembl gene IDs.
    species
        Species name for the mygene query.
    cache_path
        Optional path to a JSON file used to cache mappings across runs.
        If the file exists, it is read first; new mappings are appended
        and persisted. Useful when iterating on a notebook.

    Returns
    -------
    pd.Series
        Indexed by the *original* (possibly versioned) IDs as passed in;
        values are HGNC symbols, or NaN where mapping failed.
    """
    ids = list(ensembl_ids)
    stripped = {orig: _strip_version(orig) for orig in ids}

    # Load cache if any
    cache: dict[str, str | None] = {}
    if cache_path is not None:
        cache_path = Path(cache_path)
        if cache_path.exists():
            cache = json.loads(cache_path.read_text())

    # Identify what we still need to query
    to_query = [s for orig, s in stripped.items() if s not in cache]

    if to_query:
        mg = mygene.MyGeneInfo()
        res = mg.querymany(
            to_query,
            scopes="ensembl.gene",
            fields="symbol",
            species=species,
            as_dataframe=True,
        )
        if res.index.duplicated().any():
            res = res[~res.index.duplicated(keep="first")]
        for stripped_id, symbol in res["symbol"].items():
            cache[stripped_id] = symbol if pd.notna(symbol) else None

        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2))

    # Build the result series indexed by original (possibly versioned) IDs
    return pd.Series(
        {orig: cache.get(s) for orig, s in stripped.items()},
        name="symbol",
    )