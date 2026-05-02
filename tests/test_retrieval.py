import pytest
from omics_rag_playground.retrieval import fetch_pubmed_abstracts, _parse_pubmed_record, _save_cache, _load_cache, PubMedRecord
from pathlib import Path
from io import BytesIO
from Bio import Entrez
from dotenv import load_dotenv

# Load environment variables from .env file (e.g., NCBI_EMAIL)
load_dotenv()

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.network
def test_fetch_pubmed_abstracts_smoke():
    # Live API call. Can be skipped with: pytest -m "not network"
    records = fetch_pubmed_abstracts("BEST4 colorectal cancer", max_results=3)
    assert len(records) > 0
    assert all(isinstance(r.pmid, str) for r in records)
    assert all(isinstance(r.title, str) for r in records)
    assert all(r.pmid for r in records)
    assert all(isinstance(r.year, int) or r.year is None for r in records)

def test_parse_structured_abstract():
    xml_bytes = (FIXTURES / "pubmed_structured_abstract_29335749.xml").read_bytes()
    records = Entrez.read(BytesIO(xml_bytes))
    parsed = _parse_pubmed_record(records['PubmedArticle'][0])
    assert "BACKGROUND" not in parsed.abstract  # labels must not leak into the abstract text
    assert len(parsed.abstract) > 100

def test_parse_record_without_doi():
    xml_bytes = (FIXTURES / "pubmed_no_doi_10802651.xml").read_bytes()
    records = Entrez.read(BytesIO(xml_bytes))
    parsed = _parse_pubmed_record(records['PubmedArticle'][0])
    assert parsed.doi is None
    assert parsed.pmid  # other fields should still be populated

def test_parse_record_with_collective_authors():
    xml_bytes = (FIXTURES / "pubmed_collective_authors_23128226.xml").read_bytes()
    records = Entrez.read(BytesIO(xml_bytes))
    parsed = _parse_pubmed_record(records['PubmedArticle'][0])
    # at least one collective author (consortium) should be present
    assert len(parsed.authors) > 0

def test_cache_roundtrip(tmp_path):
    cache_file = tmp_path / "cache.json"
    record = PubMedRecord(pmid="123", title="...", abstract="...", 
                          authors=[], journal="...", year=2020, 
                          doi=None, mesh_major_topics=["test topic"])
    _save_cache(cache_file, {"123": record})
    loaded = _load_cache(cache_file)
    assert loaded["123"] == record  # dataclass __eq__ works out of the box

def test_parse_extracts_major_topics():
    xml_bytes = (FIXTURES / "pubmed_structured_abstract_29335749.xml").read_bytes()
    records = Entrez.read(BytesIO(xml_bytes))
    parsed = _parse_pubmed_record(records['PubmedArticle'][0])
    assert isinstance(parsed.mesh_major_topics, list)
    assert all(isinstance(t, str) for t in parsed.mesh_major_topics)