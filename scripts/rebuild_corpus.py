#!/usr/bin/env python
"""Rebuild the PubMed vector store from the committed corpus manifest.

The manifest (``tests/benchmark/corpus_manifest.json``) pins the corpus by PMID
and by ``sha256`` of the abstract text. It carries no abstract text: redistributing
PubMed abstracts in a public repo is a licensing grey area, while hashes give
integrity checking for free.

Records are read from the on-disk PubMed cache when present, so a warm rebuild is
fully offline. PMIDs missing from the cache are fetched from PubMed in one batched
query, which requires network access and ``NCBI_EMAIL``.

The target collection is deleted and re-created: Chroma fixes the index space at
creation time and ignores the configuration of a collection that already exists,
so an in-place rebuild would silently keep the old L2 index.

Usage:
    .venv/bin/python scripts/rebuild_corpus.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from chromadb import PersistentClient
from dotenv import load_dotenv

from omics_rag_playground.embeddings import embed_abstracts
from omics_rag_playground.retrieval import PubMedRecord, fetch_pubmed_abstracts, _load_cache
from omics_rag_playground.vector_store import (
    COSINE_CONFIGURATION,
    DEFAULT_DB_PATH,
    ingest_records,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "benchmark" / "corpus_manifest.json"
CACHE_PATH = REPO_ROOT / "data" / "processed" / "pubmed_cache.json"


def _fetch_missing(pmids: list[str]) -> dict[str, PubMedRecord]:
    """Fetch records for PMIDs absent from the cache, in one PubMed query."""
    query = " OR ".join(f"{pmid}[uid]" for pmid in pmids)
    records = fetch_pubmed_abstracts(query, max_results=len(pmids), cache_path=CACHE_PATH)
    return {r.pmid: r for r in records}


def main() -> int:
    load_dotenv()

    manifest = json.loads(MANIFEST_PATH.read_text())
    entries = manifest["records"]
    collection_name = manifest["collection_name"]
    print(f"Manifest: {len(entries)} records -> collection {collection_name!r}")

    cache = _load_cache(CACHE_PATH)
    missing = [e["pmid"] for e in entries if e["pmid"] not in cache]
    if missing:
        print(f"{len(missing)} PMIDs not cached, fetching from PubMed...")
        cache |= _fetch_missing(missing)
    else:
        print(f"All PMIDs cached at {CACHE_PATH.relative_to(REPO_ROOT)}, no network needed")

    records, genes, failures = [], [], []
    for entry in entries:
        pmid = entry["pmid"]
        record = cache.get(pmid)
        if record is None:
            failures.append(f"{pmid}: not in cache and not returned by PubMed")
            continue
        digest = hashlib.sha256(record.abstract.encode("utf-8")).hexdigest()
        if digest != entry["abstract_sha256"]:
            failures.append(f"{pmid}: abstract sha256 {digest[:12]} != manifest {entry['abstract_sha256'][:12]}")
            continue
        records.append(record)
        genes.append(entry["gene"])

    print(f"Verified {len(records)}/{len(entries)} abstract hashes")
    if failures:
        print("\nRebuild aborted, store left untouched:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    texts = [f"{r.title}\n\n{r.abstract}" for r in records]
    embeddings = embed_abstracts(texts, show_progress_bar=True)

    client = PersistentClient(path=str(DEFAULT_DB_PATH))
    existing_names = {c.name for c in client.list_collections()}
    temporary_name = f"{collection_name}__rebuild"

    if temporary_name in existing_names:
        client.delete_collection(temporary_name)

    collection = client.create_collection(
        name=temporary_name,
        configuration=COSINE_CONFIGURATION,
    )
    try:
        ingest_records(collection, records, embeddings, genes=genes)
        if collection.count() != len(records):
            raise RuntimeError(
                f"Ingested {collection.count()} of {len(records)} records"
            )
    except Exception:
        client.delete_collection(temporary_name)
        raise

    if collection_name in existing_names:
        print(f"Replacing existing collection {collection_name!r}")
        client.delete_collection(collection_name)
    collection.modify(name=collection_name)

    space = collection.configuration_json["hnsw"]["space"]
    print(f"Rebuilt {collection_name!r} at {DEFAULT_DB_PATH}: {collection.count()} documents, space={space}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
