"""Evaluation harness (Proposal §4.6, §5.2, §5.3; knowledge-base spec §23, §24).

Builds an isolated index of a corpus (with each file's front-matter metadata),
runs a fixed question set through the full pipeline (query analysis, hybrid
retrieval, reranking, grounded generation, validation) and optionally through a
no-RAG baseline, then reports:

Retrieval   Recall@k, Precision@k, MRR, nDCG@k (by source document), current-version accuracy
Answer      fact coverage, must-not-claim violations, citation accuracy, unsupported-claim rate,
            LLM-judged groundedness / hallucination rate, reply-language correctness
Behaviour   intent accuracy, clarification accuracy, safe handling of unanswerable questions
Other       latency; every metric is also broken down by question language and noise level

Question format (evaluation/*.json, key "questions"):
    {
      "id": "lost-01",
      "question": "nagarikta harayo",
      "language": "ne|en|roman_ne|mixed",
      "noise_level": "clean|medium|high",
      "expected_intent": "lost",
      "expected_sources": ["citizenship.duplicate.lost.001"],   # record ids or file names; [] = unanswerable
      "expected_answer_facts": ["जिल्ला प्रशासन कार्यालय"],      # phrases a correct answer contains
      "must_not_claim": ["Rs 5000"],                            # phrases a correct answer must NOT contain
      "expect_clarification": false                             # optional
    }
The older format (expected_source / expected_keywords / answerable) is still accepted.

Usage (from the repository root, with the backend virtualenv active):
    GEMINI_API_KEY=... python evaluation/run_eval.py --corpus knowledge_base --questions evaluation/questions_citizenship.json
    python evaluation/run_eval.py --provider fake                 # offline smoke run on sample_data
    python evaluation/run_eval.py --no-baseline --no-judge --delay 5   # quota-friendly

Results (results.json with full configuration + report.md) go to evaluation/results/<timestamp>/.
"""

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

JUDGE_PROMPT = """You are a strict evaluator of a knowledge-grounded chatbot.
Given EVIDENCE and an ANSWER, decide whether every factual claim in the ANSWER is supported by the EVIDENCE.
Statements that information is unavailable, greetings and clarifying questions count as supported.
Respond with JSON only: {"grounded": true|false, "unsupported_claims": ["..."]}"""


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=["gemini", "fake"], default=os.getenv("LLM_PROVIDER", "gemini"))
    p.add_argument("--corpus", default=str(ROOT / "sample_data"), help="folder of knowledge documents")
    p.add_argument("--questions", default=str(ROOT / "evaluation" / "questions.json"))
    p.add_argument("--profile", default=None, help="domain profile (default: DOMAIN_PROFILE or by corpus)")
    p.add_argument("--k", type=int, default=5, help="cut-off for Recall/Precision/nDCG@k")
    p.add_argument("--out", default=str(ROOT / "evaluation" / "results"))
    p.add_argument("--include-pending", action="store_true",
                   help="also index documents whose verification_status is pending")
    p.add_argument("--no-baseline", action="store_true", help="skip the no-RAG baseline")
    p.add_argument("--no-judge", action="store_true", help="skip LLM-judged groundedness")
    p.add_argument("--limit", type=int, default=0, help="only run the first N questions")
    p.add_argument("--delay", type=float, default=0.0, help="seconds to wait between questions (API quota)")
    return p.parse_args()


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))]


def mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def rate(values):
    values = [v for v in values if v is not None]
    return round(sum(1 for v in values if v) / len(values), 4) if values else None


def norm_text(text: str) -> str:
    from app.services.normalization import fold_digits

    return re.sub(r"\s+", " ", fold_digits(text or "").lower().replace(",", ""))


def load_questions(path: str) -> list[dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))["questions"]
    out = []
    for q in items:
        sources = q.get("expected_sources")
        if sources is None:
            sources = [q["expected_source"]] if q.get("expected_source") else []
        out.append({
            "id": q["id"], "question": q["question"],
            "language": q.get("language"), "noise_level": q.get("noise_level", "clean"),
            "expected_intent": q.get("expected_intent"),
            "expected_sources": list(sources),
            "expected_answer_facts": q.get("expected_answer_facts", q.get("expected_keywords", [])),
            "must_not_claim": q.get("must_not_claim", []),
            "answerable": q.get("answerable", bool(sources)),
            "expect_clarification": q.get("expect_clarification"),
        })
    return out


def retrieval_metrics(ranked_docs: list[set[str]], expected: set[str], k: int) -> dict:
    """ranked_docs: identifiers (file name, stem, record id) of each retrieved document, best first."""
    hits = [bool(ids & expected) for ids in ranked_docs]
    found = set()
    for ids in ranked_docs[:k]:
        found |= ids & expected
    # count each expected source once even if it has several identifiers
    recall = min(1.0, len(found) / len(expected)) if expected else None
    top = hits[:k]
    precision = (sum(top) / len(top)) if top else 0.0
    mrr = next((1 / (i + 1) for i, h in enumerate(hits) if h), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, h in enumerate(top) if h)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(expected), k)))
    return {"recall": recall, "precision": precision, "mrr": mrr, "ndcg": dcg / ideal if ideal else 0.0}


def main():
    args = parse_args()
    work = ROOT / "evaluation" / ".eval_index"
    shutil.rmtree(work, ignore_errors=True)
    os.environ["LLM_PROVIDER"] = args.provider
    os.environ["CHROMA_DIR"] = str(work / "chroma")
    if args.profile:
        os.environ["DOMAIN_PROFILE"] = args.profile
    elif "DOMAIN_PROFILE" not in os.environ and Path(args.corpus).resolve() == (ROOT / "sample_data").resolve():
        os.environ["DOMAIN_PROFILE"] = "customer_service"

    from app.config import get_settings
    from app.services.document_metadata import DEFAULT_TIER, normalize_metadata, split_front_matter
    from app.services.document_processing import chunk_blocks, parse_document, title_from_filename, validate_upload
    from app.services.keyword_index import BM25Index
    from app.services.llm import ChatTurn, get_llm
    from app.services.normalization import detect_language
    from app.services.profile import get_profile
    from app.services.rag import RAGPipeline
    from app.services.vector_store import VectorStore

    settings = get_settings()
    profile = get_profile()
    llm = get_llm()
    store = VectorStore(str(work / "chroma"), "evaluation")

    # ---- offline pipeline: index the corpus with its metadata ----------
    corpus = sorted(p for p in Path(args.corpus).rglob("*") if p.suffix.lower() in {".md", ".txt", ".pdf", ".docx"}
                    and not p.name.lower().startswith(("readme", "_")))
    doc_text, doc_ids, entries, skipped = {}, {}, [], []
    t0 = time.perf_counter()
    for path in corpus:
        data = path.read_bytes()
        kind = validate_upload(path.name, data, settings.max_upload_bytes)
        values = {}
        if kind in ("md", "txt"):
            values, _ = normalize_metadata(split_front_matter(data.decode("utf-8"))[0])
        if values.get("verification_status", "verified") != "verified" and not args.include_pending:
            skipped.append(path.name)
            continue
        title = values.get("title") or title_from_filename(path.name)
        source_type = values.get("source_type", "other")
        meta = {
            "document_id": path.name, "document_title": title, "record_id": values.get("record_id") or "",
            "source_type": source_type, "authority_tier": values.get("authority_tier", DEFAULT_TIER.get(source_type, 3)),
            "validity": values.get("validity_status", "current"), "verification": "verified",
            "legal_reference": values.get("legal_reference") or "", "district": values.get("district") or "",
            "jurisdiction": values.get("jurisdiction") or "", "effective_from": values.get("effective_from") or "",
            "effective_until": values.get("effective_until") or "", "source_url": values.get("source_url") or "",
            "last_verified": values.get("last_verified") or "",
        }
        blocks = parse_document(data, kind)
        pieces = chunk_blocks(blocks, settings.chunk_size, settings.chunk_overlap)
        vectors = llm.embed([f"{title}\n{p.section or ''}\n{p.text}" for p in pieces], "RETRIEVAL_DOCUMENT")
        ids = [f"{path.stem}-{p.index}" for p in pieces]
        metas = [{**meta, "section": p.section or "", "page": p.page or 0, "chunk_index": p.index} for p in pieces]
        store.upsert(ids=ids, embeddings=vectors, texts=[p.text for p in pieces], metadatas=metas)
        entries.extend(zip(ids, [p.text for p in pieces], metas))
        doc_text[path.name] = "\n\n".join(b.text for b in blocks)
        doc_ids[path.name] = {path.name, path.stem, meta["record_id"]} - {""}
        if args.delay:
            time.sleep(args.delay)
    index_ms = int((time.perf_counter() - t0) * 1000)
    print(f"Indexed {len(doc_ids)} documents into {len(entries)} chunks in {index_ms} ms"
          + (f" (skipped {len(skipped)} unverified; use --include-pending)" if skipped else ""))

    pipeline = RAGPipeline(llm, store, settings, keyword_index=BM25Index(entries), profile=profile)
    questions = load_questions(args.questions)[: args.limit or None]
    use_judge = not args.no_judge and args.provider == "gemini"

    def judge(evidence_text: str, answer: str):
        if not use_judge:
            return None
        try:
            raw = llm.generate(JUDGE_PROMPT, [ChatTurn("user", f"EVIDENCE:\n{evidence_text[:12000]}\n\nANSWER:\n{answer}")],
                               temperature=0.0, max_output_tokens=512, json_mode=True)
            match = re.search(r"\{.*\}", raw, re.S)
            return bool(json.loads(match.group(0))["grounded"]) if match else None
        except Exception as exc:  # judging is best effort
            print(f"  judge failed: {exc}")
            return None

    def facts_score(answer: str, facts: list[str]):
        if not facts:
            return None
        text = norm_text(answer)
        return sum(norm_text(f) in text for f in facts) / len(facts)

    def ids_of(doc_name: str) -> set[str]:
        return doc_ids.get(doc_name, {doc_name})

    rows = []
    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        expected = set(q["expected_sources"])
        row = {k: q[k] for k in ("id", "question", "language", "noise_level", "answerable", "expected_intent")}
        row["language"] = row["language"] or detect_language(q["question"])
        start = time.perf_counter()
        try:
            result = pipeline.answer(q["question"], [], allow_clarification=True)
        except Exception as exc:
            row["error"] = str(exc)
            rows.append(row)
            continue
        row["latency_ms"] = int((time.perf_counter() - start) * 1000)
        a = result.analysis
        row.update(answer=result.answer, kind=result.kind, confidence=result.confidence,
                   detected_language=result.language, intents=a.intents if a else [],
                   warnings=result.warnings, clarified=result.kind == "clarification")
        if q["expected_intent"]:
            row["intent_correct"] = q["expected_intent"] in row["intents"]
        if q["expect_clarification"] is not None:
            row["clarification_correct"] = row["clarified"] == bool(q["expect_clarification"])

        # retrieval: unique documents in reranked order
        ranked, seen = [], set()
        for c in result.candidates:
            name = c.metadata.get("document_id")
            if name not in seen:
                seen.add(name)
                ranked.append(ids_of(name))
        row["retrieved"] = [sorted(ids)[0] for ids in ranked[: args.k]]
        evidence_text = "\n\n".join(e.text for e in result.evidence)

        if q["answerable"]:
            if expected and not row["clarified"]:
                row.update(retrieval_metrics(ranked, expected, args.k))
            row["fact_coverage"] = facts_score(result.answer, q["expected_answer_facts"])
            cited = [ids_of(e.document_id) for e in result.cited] if not result.is_fallback else []
            row["citation_accuracy"] = (sum(bool(c & expected) for c in cited) / len(cited)) if cited and expected else None
            row["current_version_ok"] = all(e.validity_status == "current" for e in result.cited) if result.cited else None
            row["grounded"] = True if result.is_fallback or row["clarified"] else judge(evidence_text, result.answer)
            row["false_fallback"] = result.is_fallback
        else:
            grounded = True if result.is_fallback or row["clarified"] else judge(evidence_text or "(no evidence)", result.answer)
            row["grounded"] = grounded
            row["safe"] = result.is_fallback or row["clarified"] or grounded is True
        row["must_not_claim_violation"] = any(norm_text(p) in norm_text(result.answer) for p in q["must_not_claim"])
        row["unsupported_claims"] = bool(result.warnings)
        if result.kind == "answer":
            expected_lang = "en" if row["language"] == "en" else "ne"
            row["language_ok"] = detect_language(result.answer) in (("en",) if expected_lang == "en" else ("ne", "mixed"))

        if not args.no_baseline:
            start = time.perf_counter()
            try:
                base = pipeline.answer_without_rag(q["question"])
            except Exception as exc:
                base = f"ERROR: {exc}"
            row["baseline_latency_ms"] = int((time.perf_counter() - start) * 1000)
            row["baseline_answer"] = base
            reference = "\n\n".join(doc_text.get(n, "") for n, ids in doc_ids.items() if ids & expected) or "(none)"
            if q["answerable"]:
                row["baseline_fact_coverage"] = facts_score(base, q["expected_answer_facts"])
            row["baseline_grounded"] = judge(reference, base)
            row["baseline_must_not_claim_violation"] = any(norm_text(p) in norm_text(base) for p in q["must_not_claim"])
        rows.append(row)
        if args.delay:
            time.sleep(args.delay)

    metrics = aggregate(rows, args)
    by_language = {lang: aggregate([r for r in rows if r.get("language") == lang], args)["rag"]
                   for lang in sorted({r.get("language") for r in rows if r.get("language")})}
    by_noise = {lvl: aggregate([r for r in rows if r.get("noise_level") == lvl], args)["rag"]
                for lvl in sorted({r.get("noise_level") for r in rows if r.get("noise_level")})}
    config = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "provider": args.provider, "profile": profile.id,
        "generation_model": llm.model, "embedding_model": llm.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions if args.provider == "gemini" else 384,
        "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap, "top_k": settings.top_k,
        "candidate_pool": settings.candidate_pool, "rrf_k": settings.rrf_k,
        "relevance_threshold": settings.relevance_threshold, "keyword_min_coverage": settings.keyword_min_coverage,
        "max_context_chunks": settings.max_context_chunks, "query_analysis": settings.query_analysis,
        "temperature": settings.temperature, "prompt_version": settings.prompt_version, "k": args.k,
        "questions_file": str(Path(args.questions).name),
        "question_set_version": json.loads(Path(args.questions).read_text(encoding="utf-8")).get("version"),
        "corpus": {n: len(doc_text[n]) for n in sorted(doc_text)}, "skipped_unverified": skipped,
        "chunks_indexed": len(entries), "index_ms": index_ms, "llm_judge": use_judge,
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"{stamp}-{args.provider}-{profile.id}"
    out.mkdir(parents=True, exist_ok=True)
    payload = {"config": config, "metrics": metrics, "by_language": by_language, "by_noise_level": by_noise, "rows": rows}
    (out / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(render_report(config, metrics, by_language, by_noise, rows, args), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"\nReport written to {out}")


def aggregate(rows: list[dict], args) -> dict:
    ok = [r for r in rows if "error" not in r]
    ans = [r for r in ok if r["answerable"]]
    una = [r for r in ok if not r["answerable"]]
    lat = [r["latency_ms"] for r in ok if "latency_ms" in r]
    grounded = rate(r.get("grounded") for r in ans)
    rag = {
        "questions": len(rows), "errors": len(rows) - len(ok),
        f"recall@{args.k}": mean(r.get("recall") for r in ans),
        f"precision@{args.k}": mean(r.get("precision") for r in ans),
        "mrr": mean(r.get("mrr") for r in ans),
        f"ndcg@{args.k}": mean(r.get("ndcg") for r in ans),
        "current_version_accuracy": rate(r.get("current_version_ok") for r in ans),
        "fact_coverage": mean(r.get("fact_coverage") for r in ans),
        "citation_accuracy": mean(r.get("citation_accuracy") for r in ans),
        "groundedness": grounded,
        "hallucination_rate": round(1 - grounded, 4) if grounded is not None else None,
        "unsupported_claim_rate": rate(r.get("unsupported_claims") for r in ok),
        "must_not_claim_violation_rate": rate(r.get("must_not_claim_violation") for r in ok),
        "false_fallback_rate": rate(r.get("false_fallback") for r in ans),
        "unanswerable_safe_rate": rate(r.get("safe") for r in una),
        "intent_accuracy": rate(r.get("intent_correct") for r in ok),
        "clarification_accuracy": rate(r.get("clarification_correct") for r in ok),
        "clarification_rate": rate(r.get("clarified") for r in ok),
        "language_correctness": rate(r.get("language_ok") for r in ok),
        "latency_ms": {"mean": mean(lat), "p50": percentile(lat, 50), "p95": percentile(lat, 95)},
    }
    result = {"rag": rag}
    if any("baseline_answer" in r for r in ok):
        base_ground = rate(r.get("baseline_grounded") for r in ans)
        result["baseline_no_rag"] = {
            "fact_coverage": mean(r.get("baseline_fact_coverage") for r in ans),
            "groundedness": base_ground,
            "hallucination_rate": round(1 - base_ground, 4) if base_ground is not None else None,
            "must_not_claim_violation_rate": rate(r.get("baseline_must_not_claim_violation") for r in ok),
        }
    return result


def fmt(v, pct=True):
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct and isinstance(v, float) else str(v)


def render_report(config, metrics, by_language, by_noise, rows, args):
    rag, base = metrics["rag"], metrics.get("baseline_no_rag", {})
    k = args.k
    lines = [
        "# Evaluation Report", "",
        f"*Run:* {config['timestamp']} · *Profile:* {config['profile']} · *Provider:* {config['provider']} · "
        f"*Model:* {config['generation_model']} · *Embeddings:* {config['embedding_model']} "
        f"({config['embedding_dimensions']}d)", "",
        f"*Corpus:* {len(config['corpus'])} documents, {config['chunks_indexed']} chunks · *Chunking:* "
        f"{config['chunk_size']}/{config['chunk_overlap']} · *Threshold:* {config['relevance_threshold']} · "
        f"*Prompt:* {config['prompt_version']} · *LLM judge:* {'on' if config['llm_judge'] else 'off'} · "
        f"*Questions:* {config['questions_file']} (v{config['question_set_version']})", "",
    ]
    if config["provider"] == "fake":
        lines += ["> **Offline smoke run** (fake provider): numbers only verify the harness and are not a quality "
                  "measurement.", ""]
    if config["skipped_unverified"]:
        lines += [f"> {len(config['skipped_unverified'])} documents were skipped because they are not verified.", ""]
    lines += [
        "## Summary", "",
        "| Metric | RAG chatbot | Baseline (no RAG) |", "|---|---|---|",
        f"| Recall@{k} | {fmt(rag[f'recall@{k}'])} | — |",
        f"| Precision@{k} | {fmt(rag[f'precision@{k}'])} | — |",
        f"| MRR | {fmt(rag['mrr'], False)} | — |",
        f"| nDCG@{k} | {fmt(rag[f'ndcg@{k}'], False)} | — |",
        f"| Current-version accuracy | {fmt(rag['current_version_accuracy'])} | — |",
        f"| Fact coverage | {fmt(rag['fact_coverage'])} | {fmt(base.get('fact_coverage'))} |",
        f"| Citation accuracy | {fmt(rag['citation_accuracy'])} | — |",
        f"| Groundedness | {fmt(rag['groundedness'])} | {fmt(base.get('groundedness'))} |",
        f"| Hallucination rate | {fmt(rag['hallucination_rate'])} | {fmt(base.get('hallucination_rate'))} |",
        f"| Unsupported-claim rate (validator) | {fmt(rag['unsupported_claim_rate'])} | — |",
        f"| Must-not-claim violations | {fmt(rag['must_not_claim_violation_rate'])} | "
        f"{fmt(base.get('must_not_claim_violation_rate'))} |",
        f"| False fallback rate | {fmt(rag['false_fallback_rate'])} | — |",
        f"| Unanswerable handled safely | {fmt(rag['unanswerable_safe_rate'])} | — |",
        f"| Intent accuracy | {fmt(rag['intent_accuracy'])} | — |",
        f"| Clarification accuracy | {fmt(rag['clarification_accuracy'])} | — |",
        f"| Reply-language correctness | {fmt(rag['language_correctness'])} | — |",
        f"| Latency mean / p95 (ms) | {rag['latency_ms']['mean']} / {rag['latency_ms']['p95']} | — |", "",
    ]
    for title, groups in (("By question language", by_language), ("By noise level", by_noise)):
        if len(groups) > 1:
            lines += [f"## {title}", "", f"| Group | n | Recall@{k} | MRR | Fact coverage | Groundedness | Language OK |",
                      "|---|---|---|---|---|---|---|"]
            for name, m in groups.items():
                lines.append(f"| {name} | {m['questions']} | {fmt(m[f'recall@{k}'])} | {fmt(m['mrr'], False)} | "
                             f"{fmt(m['fact_coverage'])} | {fmt(m['groundedness'])} | {fmt(m['language_correctness'])} |")
            lines.append("")
    lines += ["## Per-question results", "",
              "| ID | Lang | Question | Kind | Recall | Facts | Grounded | Confidence |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['id']} | {r.get('language')} | {r['question']} | error: {r['error'][:60]} | | | | |")
            continue
        lines.append(f"| {r['id']} | {r.get('language')} | {r['question']} | {r['kind']} | {fmt(r.get('recall'))} | "
                     f"{fmt(r.get('fact_coverage'))} | {fmt(r.get('grounded'), False)} | {r.get('confidence')} |")
    failures = [r for r in rows if "error" not in r and (
        (r["answerable"] and ((r.get("recall") or 0) < 1 or (r.get("fact_coverage") is not None and r["fact_coverage"] < 1)))
        or r.get("must_not_claim_violation") or (not r["answerable"] and not r.get("safe")))]
    lines += ["", "## Failure cases", ""]
    if not failures:
        lines.append("None on this question set.")
    for r in failures:
        lines += [f"**{r['id']} — {r['question']}** (retrieved: {', '.join(r.get('retrieved', [])) or 'nothing'})", "",
                  "> " + r.get("answer", "")[:600].replace("\n", "\n> "), ""]
    lines += ["", "*The baseline is a direct LLM chat without retrieval on the same questions (Proposal §5.3); its "
              "groundedness is judged against the expected source documents.*"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
