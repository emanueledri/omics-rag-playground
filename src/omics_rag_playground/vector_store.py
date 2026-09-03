"""ChromaDB-backed vector store for PubMed abstract embeddings."""

from pathlib import Path
from typing import Callable
import numpy as np
from omics_rag_playground.retrieval import PubMedRecord

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection

DEFAULT_COLLECTION_NAME = "pubmed_abstracts_no_mesh"
# Anchored on the package location, not the CWD, so the defaults resolve
# identically from the repo root, from notebooks/ and from scripts/.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "chroma_db"

COSINE_CONFIGURATION = {"hnsw": {"space": "cosine"}}

def get_or_create_collection(db_path: str | Path = DEFAULT_DB_PATH, 
                             collection_name: str = DEFAULT_COLLECTION_NAME,
                             ) -> Collection:
    """Get or create a Chroma collection for storing PubMed abstract embeddings.

    New collections are created with the cosine index, so reported distances
    are ``1 - cos``. The index space is fixed at creation time: on a collection
    that already exists Chroma ignores the configuration and returns it as
    built, so switching an existing collection to cosine requires deleting and
    re-ingesting it (see ``scripts/rebuild_corpus.py``).

    Args:
        db_path: Path to the Chroma database directory.
        collection_name: Name of the collection to get or create.

    Returns:
        A Chroma collection object.
    """

    client = PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name=collection_name,
                                                 configuration=COSINE_CONFIGURATION)

    return collection

def ingest_records(collection: Collection, records: list[PubMedRecord], embeddings: np.ndarray, 
                   genes: list[str] | None=None, text_builder=lambda r: f"{r.title}\n\n{r.abstract}"):
    """Ingest PubMed records and their embeddings into a Chroma collection.
    year may be None for records with unparseable PubDate

    Args:
        collection: A Chroma collection object.
        records: A list of PubMedRecord objects to ingest.
        embeddings: ndarray shape (N, D) of embedding vectors corresponding to the records.
        genes: A list of gene names corresponding to the records.
        text_builder: A function that takes a PubMedRecord and returns a string
            to be stored in the collection (default is title + abstract).
    """

    ids = [r.pmid for r in records]
    documents = [text_builder(r) for r in records]
    metadatas = [
        {"year": r.year, "journal": r.journal, "gene": g} 
        for r, g in zip(records, genes or [None] * len(records))
    ]

    collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

def query_collection(collection: Collection, query_text: str, 
                     embed_fn: Callable[[list[str]], np.ndarray], n_results: int = 5)-> list[tuple]:
    """Query a Chroma collection for relevant abstracts given a text query.

    Args:
        collection: A Chroma collection object.
        query_text: The input text query to search for.
        embed_fn: A function that takes a list of strings and returns an array of embedding vectors.
        n_results: The number of top results to return.

    Returns:
        A list of the top n_results relevant abstracts.

    Raises:
        ValueError: If the collection is empty. Querying an empty collection
            returns no results, which silently looks like "nothing is relevant"
            to every downstream caller; a missing or unbuilt store must fail loudly.
    """
    if collection.count() == 0:
        raise ValueError(
            f"Collection {collection.name!r} is empty. "
            "Querying it would return no results and every downstream caller "
            "would treat that as an absence of relevant literature. "
            "Run scripts/rebuild_corpus.py to build it, or check the collection "
            "name and database path."
        )

    query_embedding = embed_fn([query_text])[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )
    results = list(zip(results['ids'][0], results['documents'][0], 
                       results['metadatas'][0], results['distances'][0]))
    # ascending order by distance (most relevant first)
    results.sort(key=lambda x: x[3])

    return results