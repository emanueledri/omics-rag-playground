"""ChromaDB-backed vector store for PubMed abstract embeddings."""

from pathlib import Path
from typing import Callable
import numpy as np
from omics_rag_playground.retrieval import PubMedRecord

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection

DEFAULT_COLLECTION_NAME = "pubmed_abstracts"
DEFAULT_DB_PATH = Path("../data/processed/chroma_db")

def get_or_create_collection(db_path: str | Path = DEFAULT_DB_PATH, 
                             collection_name: str = DEFAULT_COLLECTION_NAME,
                             ) -> Collection:
    """Get or create a Chroma collection for storing PubMed abstract embeddings.

    Args:
        db_path: Path to the Chroma database directory.
        collection_name: Name of the collection to get or create.

    Returns:
        A Chroma collection object.
    """

    client = PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(name=collection_name)

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
    """
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