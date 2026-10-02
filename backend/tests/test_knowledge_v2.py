"""Source metadata, verification, versioning, query analysis, hybrid retrieval,
clarification and answer validation (spec steps 1, 3, 4, 5)."""

import json
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.services import llm as llm_module
from app.services import rag as rag_module
from app.services.answer_validation import validate_answer
from app.services.keyword_index import BM25Index
from app.services.normalization import Normalizer, detect_language, tokenize
from app.services.profile import load_profile
from app.services.query_analysis import QueryAnalysis
from app.services.vector_store import VectorStore

RECORD = """---
id: test.lost.001
title: Lost certificate replacement
source_type: regulation
section: Rule 9
issuing_authority: Ministry of Home Affairs
jurisdiction: Nepal
status: current
effective_from: 2079-01-01
last_verified: 2026-10-01
source_url: https://example.gov.np/regulation
verification_status: pending
amendment_status: amended
tags: [lost, duplicate]
---
# Lost certificate replacement

A person whose zorblax certificate is lost may apply for a replacement zorblax certificate at the issuing office
within 35 days, paying a fee of Rs 100.
"""


def ask(client, headers, message, conversation_id=None):
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    r = client.post("/api/chat", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ----------------------------------------------------------- step 1 -------
def test_front_matter_metadata_and_verification_gate(client, admin_headers, user_headers, knowledge, monkeypatch):
    r = client.post("/api/documents/upload", headers=admin_headers,
                    files={"file": ("lost.md", RECORD.encode(), "text/markdown")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["title"] == "Lost certificate replacement"
    assert doc["source_type"] == "regulation" and doc["authority_tier"] == 1  # tier defaulted from type
    assert doc["legal_reference"] == "Rule 9" and doc["last_verified"] == "2026-10-01"
    assert doc["verification_status"] == "pending" and doc["record_id"] == "test.lost.001"
    assert set(doc["tags"]) >= {"lost", "duplicate"}

    # pending documents are never used as evidence
    assert ask(client, user_headers, "How do I replace a lost zorblax certificate?")["assistant_message"]["is_fallback"]

    # verifying is a metadata-only change: no re-embedding
    calls = []
    provider = llm_module.get_llm()
    original = provider.embed
    monkeypatch.setattr(provider, "embed", lambda texts, task: calls.append(task) or original(texts, task))
    r = client.put(f"/api/documents/{doc['id']}", headers=admin_headers, data={"verification_status": "verified"})
    assert r.status_code == 200 and r.json()["verification_status"] == "verified"
    assert "RETRIEVAL_DOCUMENT" not in calls

    answer = ask(client, user_headers, "How do I replace a lost zorblax certificate?")["assistant_message"]
    assert not answer["is_fallback"]
    cite = answer["citations"][0]
    assert cite["source_type"] == "regulation" and cite["legal_reference"] == "Rule 9"
    assert cite["source_url"] == "https://example.gov.np/regulation" and cite["last_verified"] == "2026-10-01"
    assert answer["confidence"] == "HIGH"


def test_invalid_metadata_is_rejected(client, admin_headers):
    r = client.post("/api/documents/upload", headers=admin_headers, data={"source_type": "blog-post"},
                    files={"file": ("x.txt", b"some text here", "text/plain")})
    assert r.status_code == 400 and "source_type" in r.json()["detail"]
    r = client.post("/api/documents/upload", headers=admin_headers, data={"source_url": "javascript:alert(1)"},
                    files={"file": ("y.txt", b"other text here", "text/plain")})
    assert r.status_code == 400


def test_new_version_by_record_id_supersedes_old(client, admin_headers, user_headers, knowledge):
    v1 = RECORD.replace("test.lost.001", "test.fee.001").replace("verification_status: pending",
                                                                 "verification_status: verified")
    v1 = v1.replace("zorblax", "quixel")
    d1 = client.post("/api/documents/upload", headers=admin_headers,
                     files={"file": ("fee.md", v1.encode(), "text/markdown")}).json()
    v2 = v1.replace("Rs 100", "Rs 250").replace("effective_from: 2079-01-01", "effective_from: 2082-04-01")
    d2 = client.post("/api/documents/upload", headers=admin_headers,
                     files={"file": ("fee-v2.md", v2.encode(), "text/markdown")}).json()
    assert d2["version"] == 2 and d2["supersedes_id"] == d1["id"]
    old = client.get(f"/api/documents/{d1['id']}", headers=admin_headers).json()
    assert old["validity_status"] == "superseded" and old["effective_until"] == "2082-04-01"

    answer = ask(client, user_headers, "What is the fee to replace a lost quixel certificate?")["assistant_message"]
    assert "250" in answer["content"]
    assert d1["id"] not in {c["document_id"] for c in answer["citations"]}  # superseded version never cited


def test_schema_upgrade_adds_missing_columns():
    from app.database import _add_missing_columns

    engine = create_engine(f"sqlite:///{tempfile.mkdtemp()}/old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE documents (id VARCHAR(36) PRIMARY KEY, title VARCHAR(255))"))
        conn.execute(text("INSERT INTO documents (id, title) VALUES ('d1', 'Old')"))
    added = _add_missing_columns(engine)
    assert "documents.validity_status" in added and "documents.verification_status" in added
    cols = {c["name"] for c in inspect(engine).get_columns("documents")}
    assert {"source_type", "authority_tier", "source_url", "lineage_id"} <= cols
    with engine.connect() as conn:
        row = conn.execute(text("SELECT validity_status, verification_status, authority_tier FROM documents")).one()
    assert tuple(row) == ("current", "verified", 3)


# ----------------------------------------------------------- step 3 -------
def test_language_detection_and_normalization():
    assert detect_language("नागरिकता कसरी बनाउने?") == "ne"
    assert detect_language("nagarikta kasari banaune?") == "roman_ne"
    assert detect_language("mero citizenship lost vayo, duplicate kasari banaune?") == "roman_ne"
    assert detect_language("How can I obtain Nepali citizenship?") == "en"
    assert tokenize("nagarikataa") == tokenize("nagarikta")[:0] + ["nagarikata"]
    assert tokenize("नागरिकताको रु. १००") == ["नागरिकता", "रु", "100"]
    norm = Normalizer(load_profile("nepal_citizenship").synonyms)
    expanded = norm.expand(tokenize("nagrikta harayo"))
    assert "नागरिकता" in expanded and "हरायो" in expanded and "lost" in expanded


def test_analysis_output_is_parsed_and_validated():
    from app.services.query_analysis import _parse

    profile = load_profile("nepal_citizenship")
    raw = json.dumps({
        "language": "roman_ne", "standalone_question": "How to get citizenship by descent?",
        "search_queries": ["वंशजको नागरिकता", "citizenship by descent"], "keywords": ["वंशज", "descent"],
        "intents": ["descent", "made_up_intent"], "facts": {"age": 17, "favourite_colour": "blue"},
        "district": "Kathmandu", "time_reference": None, "source_preference": "both",
        "missing_facts": [], "needs_clarification": True, "clarifying_questions": [],
    })
    a = _parse(raw, "mero baba ko citizenship xa, ma 17 barsa ko xu", profile)
    assert a.intents == ["descent"]                  # unknown intents dropped
    assert a.facts == {"age": 17}                     # unknown fact keys dropped
    assert a.needs_clarification is False             # no questions -> no clarification
    assert a.queries()[0].startswith("mero baba")     # the original query is preserved first


# ----------------------------------------------------------- step 4 -------
def _pipeline(entries, profile_name="nepal_citizenship"):
    store = VectorStore(tempfile.mkdtemp(), "unit")
    provider = llm_module.FakeProvider(get_settings())
    ids, texts, metas = zip(*entries)
    store.upsert(list(ids), provider.embed(list(texts), "RETRIEVAL_DOCUMENT"), list(texts), list(metas))
    return rag_module.RAGPipeline(provider, store, keyword_index=BM25Index(list(entries)),
                                  profile=load_profile(profile_name))


def _meta(doc_id, title, **extra):
    base = {"document_id": doc_id, "document_title": title, "verification": "verified", "validity": "current",
            "authority_tier": 1, "source_type": "regulation", "district": ""}
    return {**base, **extra}


def test_hybrid_keyword_search_matches_roman_nepali_to_devanagari():
    pipe = _pipeline([
        ("c1", "नागरिकता हराएमा प्रतिलिपि लिन जिल्ला प्रशासन कार्यालयमा निवेदन दिनुपर्छ।", _meta("d1", "प्रतिलिपि")),
        ("c2", "Delivery is free above Rs. 5,000 inside the valley.", _meta("d2", "Shipping", authority_tier=4)),
    ])
    candidates, evidence = pipe.retrieve(QueryAnalysis(original="nagrikta harayo pratilipi"))
    assert evidence and evidence[0].chunk_id == "c1"
    assert candidates[0].keyword_score > 0 and candidates[0].vector_score < 0.2  # found by BM25, not by vectors


def test_reranking_prefers_primary_law_and_current_versions():
    text = "Citizenship certificate replacement requires an application and a recommendation."
    pipe = _pipeline([
        ("law", text + " (law)", _meta("d1", "Regulation", authority_tier=1)),
        ("blog", text + " (blog)", _meta("d2", "Blog", authority_tier=5, source_type="informal")),
        ("old", text + " (old)", _meta("d3", "Old rule", validity="superseded")),
    ])
    candidates, evidence = pipe.retrieve(QueryAnalysis(original="citizenship certificate replacement recommendation"))
    assert evidence[0].chunk_id == "law"
    assert "old" not in {c.chunk_id for c in candidates}  # superseded excluded for current questions
    _, historical = pipe.retrieve(QueryAnalysis(original="citizenship certificate replacement recommendation",
                                                time_reference="2063"))
    assert "old" in {e.chunk_id for e in historical}


def test_district_filter_excludes_other_districts():
    text = "The District Administration Office asks for the ward recommendation and two photographs."
    pipe = _pipeline([
        ("ktm", text + " Kathmandu", _meta("d1", "DAO Kathmandu charter", district="Kathmandu", authority_tier=3)),
        ("pan", text + " Panchthar", _meta("d2", "DAO Panchthar charter", district="Panchthar", authority_tier=3)),
    ])
    _, evidence = pipe.retrieve(QueryAnalysis(original="ward recommendation photographs office", district="Kathmandu"))
    assert [e.chunk_id for e in evidence] == ["ktm"]


# ----------------------------------------------------------- step 5 -------
def test_clarifying_question_once_then_answer(client, user_headers, knowledge, monkeypatch):
    real = rag_module.analyze_query

    def needs_more(llm, profile, question, history, sanitize):
        a = real(llm, profile, question, history, sanitize)
        a.needs_clarification, a.clarifying_questions = True, ["Which product is it?"]
        a.missing_facts = ["product"]
        return a

    monkeypatch.setattr(rag_module, "analyze_query", needs_more)
    first = ask(client, user_headers, "Can I return it?")
    msg = first["assistant_message"]
    assert msg["kind"] == "clarification" and msg["confidence"] == "NEEDS_CLARIFICATION"
    assert "Which product is it?" in msg["content"] and not msg["citations"]
    # The follow-up is answered even if analysis still wants more facts (no clarification loops).
    second = ask(client, user_headers, "A laptop, how many days do I have to return it?", first["conversation_id"])
    assert second["assistant_message"]["kind"] in ("answer", "fallback")


def test_unsupported_figures_are_flagged(client, user_headers, knowledge, monkeypatch):
    provider = llm_module.get_llm()
    real = provider.generate

    def invent(system, turns, **kw):
        if "QUERY_ANALYSIS" in system:
            return real(system, turns, **kw)
        return "Refunds are processed within 5 working days [1] and cost Rs 999 [1]."

    monkeypatch.setattr(provider, "generate", invent)
    msg = ask(client, user_headers, "How long does it take to get my refund?")["assistant_message"]
    assert "Rs 999" in msg["content"].split("⚠️")[1]  # flagged in the verification note
    assert msg["confidence"] == "LOW"


def test_validate_answer_unit():
    r = validate_answer("शुल्क रु. १०० [1]। ३५ दिन भित्र [3]. Section 7 says so [1].",
                        {1: "दस्तुर रु. 100", 2: "other"})
    assert r.invalid_citations == [3] and "[3]" not in r.answer
    assert "35 दिन" in r.unsupported and "Section 7" in r.unsupported
    assert not any("100" in u for u in r.unsupported)


def test_localized_small_talk_and_profile_endpoint(client, user_headers):
    msg = ask(client, user_headers, "नमस्ते")["assistant_message"]
    assert msg["kind"] == "small_talk" and "नमस्ते" in msg["content"]
    profile = client.get("/api/profile").json()
    assert profile["id"] == "customer_service" and profile["suggestions"]


@pytest.mark.parametrize("name", ["nepal_citizenship", "customer_service"])
def test_profiles_load(name):
    p = load_profile(name)
    assert p.assistant_name and p.text("fallback_messages", "roman_ne") and p.text("fallback_messages", "en")
