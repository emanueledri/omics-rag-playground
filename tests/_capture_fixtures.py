# tests/_capture_fixtures.py
"""
One-shot script to capture real PubMed XML responses as test fixtures.
Run from repo root: python tests/_capture_fixtures.py
Requires NCBI_EMAIL env var (and optionally NCBI_API_KEY).
"""
import os
from pathlib import Path
from Bio import Entrez
from dotenv import load_dotenv

# Load environment variables from .env file (e.g., NCBI_EMAIL)
load_dotenv()

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# PMIDs chosen to cover interesting cases.
# Change these if you want to capture different specific cases.
PMIDS = {
    "structured_abstract": "29335749",  # multi-section abstract
    "flat_abstract": "24658644",        # single-block abstract
    "no_doi": "10802651",               # older paper, often without DOI
    "collective_authors": "23128226",   # consortium paper
}


def main() -> None:
    email = os.getenv("NCBI_EMAIL")
    if not email:
        raise SystemExit("Set NCBI_EMAIL env var before running.")
    Entrez.email = email
    if api_key := os.getenv("NCBI_API_KEY"):
        Entrez.api_key = api_key

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    for label, pmid in PMIDS.items():
        out_path = FIXTURES_DIR / f"pubmed_{label}_{pmid}.xml"
        print(f"Fetching PMID {pmid} -> {out_path.name}")
        with Entrez.efetch(db="pubmed", id=pmid, rettype="xml", retmode="xml") as handle:
            out_path.write_bytes(handle.read())

    print(f"\nDone. {len(PMIDS)} fixtures saved in {FIXTURES_DIR}/")


if __name__ == "__main__":
    main()