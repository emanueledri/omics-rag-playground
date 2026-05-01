"""PubMed abstract retrieval via NCBI E-utilities, with on-disk caching by PMID."""

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os

from Bio import Entrez

def _configure_entrez() -> None:
    email = os.getenv("NCBI_EMAIL")
    if not email:
        raise RuntimeError(
            "NCBI_EMAIL environment variable must be set. "
            "NCBI requires an email for E-utilities access."
        )
    Entrez.email = email
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        Entrez.api_key = api_key

@dataclass(frozen=True)
class PubMedRecord:
    pmid: str
    title: str
    abstract: str
    authors: list[str]
    year: int | None
    doi: str | None
    journal: str

def fetch_pubmed_abstracts(
    query: str,
    max_results: int = 20,
    cache_path: str | Path | None = None,
) -> list[PubMedRecord]:
    """Fetch PubMed records for a query, using an optional on-disk cache.

    Args:
        query: PubMed search query passed to the NCBI ESearch endpoint.
        max_results: Maximum number of PMIDs to retrieve from the search.
        cache_path: Optional path to a JSON cache file keyed by PMID.
            Recommended convention: ``Path("data/processed/pubmed_cache.json")``.

    Returns:
        A list of ``PubMedRecord`` objects ordered to match the PMID search results.

    Raises:
        RuntimeError: If the ``NCBI_EMAIL`` environment variable is not set.
    """

    _configure_entrez()

    # Load cache if any cache: 
    cache_path = Path(cache_path) if cache_path else None
    cache = _load_cache(cache_path) if cache_path else {}

    # Search for gene-related papers
    search_handle = Entrez.esearch(db="pubmed",term=query,
                                   retmax=max_results)
    with Entrez.esearch(db="pubmed", term=query, retmax=max_results) as search_handle:
        search_results = Entrez.read(search_handle)
    pmids = search_results["IdList"]

    if not pmids:
        return []

    cached_records, missing_pmids = [], []

    for pmid in pmids:
        if pmid in cache:
            cached_records.append(cache[pmid])
        else:
            missing_pmids.append(pmid)

    if missing_pmids:
        new_records = _efetch_and_parse(missing_pmids)
        if cache_path:
            _save_cache(cache_path, cache | {r.pmid: r for r in new_records})
    else:
        new_records = []
    
    all_records = {**{r.pmid: r for r in cached_records}, **{r.pmid: r for r in new_records}}
    return [all_records[pmid] for pmid in pmids if pmid in all_records]
    
    
def _efetch_and_parse(missing_pmids: list[str]) -> list[PubMedRecord]:
    """Fetch and parse PubMed records for PMIDs not found in the cache.

    Args:
        missing_pmids: Iterable of PubMed IDs to retrieve via the NCBI
            EFetch endpoint.

    Returns:
        A list of ``PubMedRecord`` instances parsed from the fetched XML
        response, in the order returned by PubMed.
    """
    with Entrez.efetch(db="pubmed", id=missing_pmids, rettype="xml", retmode="xml") as fetch_handle:
        records = Entrez.read(fetch_handle)

    # Parse records into PubMedRecord dataclass instances
    parsed_records = []
    for article in records["PubmedArticle"]:
        record = _parse_pubmed_record(article)
        parsed_records.append(record)

    return parsed_records

def _parse_pubmed_record(article: dict) -> PubMedRecord:
    """Parse a single PubMed article XML record into a PubMedRecord dataclass."""

    medline = article["MedlineCitation"]
    pmid = str(medline["PMID"])

    article_data = medline["Article"]

    title = str(article_data.get("ArticleTitle", ""))

    abstract_field = article_data.get('Abstract', {}).get('AbstractText', None)
    if abstract_field is None:
        abstract = ""
    elif isinstance(abstract_field, list):
        abstract = " ".join(str(part) for part in abstract_field)
    else:
        abstract = str(abstract_field)

    def _format_author(author: dict) -> str | None:
        if 'CollectiveName' in author:
            return str(author['CollectiveName'])
        last = author.get('LastName')
        initials = author.get('Initials')
        if last and initials:
            return f"{last} {initials}"
        if last:
            return str(last)
        return None  # autore corrotto, skippa

    authors = [
        formatted
        for author in article_data.get('AuthorList', [])
        if (formatted := _format_author(author)) is not None
    ]

    pub_date = article_data['Journal']['JournalIssue']['PubDate']
    year_str = pub_date.get('Year')  # primo tentativo
    if year_str is None:
        medline_date = pub_date.get('MedlineDate', '')
        # MedlineDate tipo "2024 Spring" → estrai i primi 4 char se digit
        year_str = medline_date[:4] if medline_date[:4].isdigit() else None
    year = int(year_str) if year_str else None

    doi = None
    for article_id in article.get('PubmedData', {}).get('ArticleIdList', []):
        if article_id.attributes.get('IdType') == 'doi':
            doi = str(article_id)
            break

    journal = str(article_data.get("Journal", {}).get("Title", ""))

    record = PubMedRecord(
        pmid=pmid,
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        doi=doi,
        journal=journal,
    )

    return record

def _save_cache(path: Path, cache: dict[str, PubMedRecord]) -> None:
    """Save the cache of PubMedRecord instances to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {pmid: asdict(record) for pmid, record in cache.items()}
    path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False))

def _load_cache(path: Path) -> dict[str, PubMedRecord]:
    """Load the cache of PubMedRecord instances from a JSON file."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {pmid: PubMedRecord(**data) for pmid, data in raw.items()}