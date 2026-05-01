"""Biomedical sentence embeddings for PubMed abstracts.

Uses NeuML/pubmedbert-base-embeddings — a sentence-transformers
fine-tune of PubMedBERT, optimized for similarity search over
biomedical text. See docs/design-notes.md for model selection rationale.
"""

from __future__ import annotations
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer


DEFAULT_MODEL_NAME = "NeuML/pubmedbert-base-embeddings"


@lru_cache(maxsize=2)
def _load_model(model_name: str = DEFAULT_MODEL_NAME) -> SentenceTransformer:
    """Load and cache a SentenceTransformer model.
    
    The cache prevents re-downloading and re-instantiating the model
    on repeated calls within the same process. Two slots is enough
    headroom for swapping models in ablation experiments without
    evicting the default.
    """
    return SentenceTransformer(model_name)


def embed_abstracts(
    abstracts: list[str],
    model_name: str = DEFAULT_MODEL_NAME,
    batch_size: int = 32,
    show_progress_bar: bool = False,
) -> np.ndarray:
    """Embed a list of abstract texts into dense vectors.
    
    Parameters
    ----------
    abstracts
        List of strings to embed. Empty strings are tolerated by
        the underlying model but produce low-quality vectors;
        callers should filter beforehand.
    model_name
        HuggingFace model id. Defaults to a PubMed-fine-tuned model
        suitable for biomedical retrieval.
    batch_size
        Number of inputs per forward pass. 32 is a safe default for
        CPU and most GPUs; increase if memory allows.
    show_progress_bar
        Whether to display a tqdm bar during encoding. Useful in
        notebooks, noisy in tests.
    
    Returns
    -------
    np.ndarray
        Float32 array of shape ``(len(abstracts), embedding_dim)``.
        For NeuML/pubmedbert-base-embeddings, ``embedding_dim == 768``.
    """
    if not abstracts:
        return np.empty((0, 0), dtype=np.float32)
    
    model = _load_model(model_name)
    embeddings = model.encode(
        abstracts,
        batch_size=batch_size,
        show_progress_bar=show_progress_bar,
        convert_to_numpy=True,
        normalize_embeddings=True, 
    )
    return embeddings.astype(np.float32)