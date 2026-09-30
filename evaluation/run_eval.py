"""Evaluation harness (Proposal §4.6, §5.2, §5.3).

Builds an isolated index of a corpus, runs a fixed question set through the
RAG pipeline and through a no-RAG Gemini baseline, and reports:

* Retrieval relevance  - hit rate: expected document among retrieved evidence
* Context precision    - share of retrieved evidence chunks from the expected document
* Answer correctness   - expected keywords present in the answer
* Groundedness         - LLM-judge verdict that every claim is supported by evidence
* Hallucination rate   - 1 - groundedness (answered questions)
* Failure handling     - safe behaviour on unanswerable questions
* Latency              - mean / p50 / p95 end-to-end time

Usage (from the repository root):
    GEMINI_API_KEY=... python evaluation/run_eval.py
    python evaluation/run_eval.py --provider fake          # offline smoke run
    python evaluation/run_eval.py --no-baseline --no-judge  # cheaper run

Results (JSON with full configuration + Markdown report) are written to
evaluation/results/<timestamp>/ so they can be kept under version control.
"""

import argparse
import json
import os
import re
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

JUDGE_PROMPT = """You are a strict evaluator of a customer-service chatbot.
Given EVIDENCE and an ANSWER, decide whether every factual claim in the ANSWER is supported by the EVIDENCE.
Statements that the information is unavailable, greetings and requests for clarification count as supported.
Respond with JSON only: {"grounded": true|false, "unsupported_claims": ["..."]}"""


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=["gemini", "fake"], default=os.getenv("LLM_PROVIDER", "gemini"))
    p.add_argument("--corpus", default=str(ROOT / "sample_data"))
    p.add_argument("--questions", default=str(ROOT / "evaluation" / "questions.json"))
    p.add_argument("--out", default=str(ROOT / "evaluation" / "results"))
    p.add_argument("--no-baseline", action="store_true", help="skip the no-RAG Gemini baseline")
    p.add_argument("--no-judge", action="store_true", help="skip LLM-judged groundedness")
    p.add_argument("--delay", type=float, default=0.0, help="seconds to wait between questions (API quota)")
    return p.parse_args()


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


def main():
    args = parse_args()
    work = ROOT / "evaluation" / ".eval_index"
    shutil.rmtree(work, ignore_errors=True)
    os.environ["LLM_PROVIDER"] = args.provider
    os.environ["CHROMA_DIR"] = str(work / "chroma")

    from app.config import get_settings
    from app.services.document_processing import chunk_blocks, parse_document, title_from_filename, validate_upload
    from app.services.llm import ChatTurn, get_llm
    from app.services.rag import RAGPipeline
    from app.services.vector_store import VectorStore

    settings = get_settings()
    llm = get_llm()
    store = VectorStore(str(work / "chroma"), "evaluation")

    # ---- offline pipeline: index the corpus -----------------------------
    corpus = sorted(p for p in Path(args.corpus).iterdir() if p.suffix.lower() in {".md", ".txt", ".pdf", ".docx"})
    title_to_file, doc_text = {}, {}
    total_chunks = 0
    t0 = time.perf_counter()
    for path in corpus:
        data = path.read_bytes()
        kind = validate_upload(path.name, data, settings.max_upload_bytes)
        title = title_from_filename(path.name)
        blocks = parse_document(data, kind)
        pieces = chunk_blocks(blocks, settings.chunk_size, settings.chunk_overlap)
        vectors = llm.embed([f"{title}\n{p.section or ''}\n{p.text}" for p in pieces], "RETRIEVAL_DOCUMENT")
        store.upsert(
            ids=[f"{path.stem}-{p.index}" for p in pieces],
            embeddings=vectors,
            texts=[p.text for p in pieces],
            metadatas=[{"document_id": path.name, "document_title": title, "section": p.section, "page": p.page}
                       for p in pieces],
        )
        title_to_file[title] = path.name
        doc_text[path.name] = "\n\n".join(b.text for b in blocks)
        total_chunks += len(pieces)
    index_ms = int((time.perf_counter() - t0) * 1000)
    print(f"Indexed {len(corpus)} documents into {total_chunks} chunks in {index_ms} ms")

    pipeline = RAGPipeline(llm, store, settings)
    questions = json.loads(Path(args.questions).read_text())["questions"]
    use_judge = not args.no_judge and args.provider == "gemini"
    use_baseline = not args.no_baseline

    def judge(evidence_text: str, answer: str):
        if not use_judge:
            return None
        try:
            raw = llm.generate(JUDGE_PROMPT, [ChatTurn("user", f"EVIDENCE:\n{evidence_text}\n\nANSWER:\n{answer}")],
                               temperature=0.0, max_output_tokens=512)
            match = re.search(r"\{.*\}", raw, re.S)
            return bool(json.loads(match.group(0))["grounded"]) if match else None
        except Exception as exc:  # judging is best effort
            print(f"  judge failed: {exc}")
            return None

    def keyword_score(answer: str, keywords: list[str]) -> float:
        if not keywords:
            return 0.0
        norm = answer.lower().replace(",", "")
        return sum(k.lower().replace(",", "") in norm for k in keywords) / len(keywords)

    rows = []
    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        row = {"id": q["id"], "question": q["question"], "answerable": q["answerable"]}
        start = time.perf_counter()
        try:
            result = pipeline.answer(q["question"], [])
        except Exception as exc:
            row.update(error=str(exc))
            rows.append(row)
            continue
        row["rag_latency_ms"] = int((time.perf_counter() - start) * 1000)
        row["rag_answer"] = result.answer
        row["rag_fallback"] = result.is_fallback
        row["retrieved"] = [{"file": title_to_file.get(e.document_title), "score": e.score} for e in result.evidence]
        evidence_text = "\n\n".join(e.text for e in result.evidence)

        if q["answerable"]:
            files = [r["file"] for r in row["retrieved"]]
            row["retrieval_hit"] = q["expected_source"] in files
            row["context_precision"] = (files.count(q["expected_source"]) / len(files)) if files else 0.0
            row["rag_correctness"] = keyword_score(result.answer, q["expected_keywords"])
            row["rag_grounded"] = judge(evidence_text, result.answer) if not result.is_fallback else True
        else:
            grounded = True if result.is_fallback else judge(evidence_text or "(no evidence)", result.answer)
            row["rag_grounded"] = grounded
            row["rag_safe"] = result.is_fallback or grounded is True

        if use_baseline:
            start = time.perf_counter()
            try:
                base = pipeline.answer_without_rag(q["question"])
            except Exception as exc:
                base = f"ERROR: {exc}"
            row["baseline_latency_ms"] = int((time.perf_counter() - start) * 1000)
            row["baseline_answer"] = base
            reference = doc_text.get(q.get("expected_source", ""), "") or "\n\n".join(doc_text.values())
            if q["answerable"]:
                row["baseline_correctness"] = keyword_score(base, q["expected_keywords"])
            row["baseline_grounded"] = judge(reference, base)
            if not q["answerable"]:
                row["baseline_safe"] = row["baseline_grounded"] is True
        rows.append(row)
        if args.delay:
            time.sleep(args.delay)

    # ---- aggregate --------------------------------------------------------
    ans = [r for r in rows if r["answerable"] and "error" not in r]
    una = [r for r in rows if not r["answerable"] and "error" not in r]

    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None

    def rate(values):
        values = [v for v in values if v is not None]
        return round(sum(1 for v in values if v) / len(values), 4) if values else None

    rag_lat = [r["rag_latency_ms"] for r in rows if "rag_latency_ms" in r]
    metrics = {
        "rag": {
            "retrieval_relevance_hit_rate": rate(r["retrieval_hit"] for r in ans),
            "context_precision": mean(r["context_precision"] for r in ans),
            "answer_correctness": mean(r["rag_correctness"] for r in ans),
            "groundedness": rate(r["rag_grounded"] for r in ans),
            "hallucination_rate": (round(1 - rate(r["rag_grounded"] for r in ans), 4)
                                   if rate(r["rag_grounded"] for r in ans) is not None else None),
            "false_fallback_rate": rate(r["rag_fallback"] for r in ans),
            "failure_handling_safe_rate": rate(r["rag_safe"] for r in una),
            "latency_ms": {"mean": mean(rag_lat), "p50": percentile(rag_lat, 50), "p95": percentile(rag_lat, 95)},
        },
        "errors": sum(1 for r in rows if "error" in r),
    }
    if use_baseline:
        base_lat = [r["baseline_latency_ms"] for r in rows if "baseline_latency_ms" in r]
        base_ground = rate(r.get("baseline_grounded") for r in ans)
        metrics["baseline_no_rag"] = {
            "answer_correctness": mean(r.get("baseline_correctness") for r in ans),
            "groundedness": base_ground,
            "hallucination_rate": round(1 - base_ground, 4) if base_ground is not None else None,
            "failure_handling_safe_rate": rate(r.get("baseline_safe") for r in una),
            "latency_ms": {"mean": mean(base_lat), "p50": percentile(base_lat, 50), "p95": percentile(base_lat, 95)},
        }

    config = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "generation_model": llm.model,
        "embedding_model": llm.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions if args.provider == "gemini" else 384,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k": settings.top_k,
        "relevance_threshold": settings.relevance_threshold,
        "max_context_chunks": settings.max_context_chunks,
        "temperature": settings.temperature,
        "prompt_version": settings.prompt_version,
        "question_set_version": json.loads(Path(args.questions).read_text()).get("version"),
        "corpus": {p.name: len(p.read_bytes()) for p in corpus},
        "chunks_indexed": total_chunks,
        "index_ms": index_ms,
        "llm_judge": use_judge,
    }

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"{stamp}-{args.provider}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"config": config, "metrics": metrics, "rows": rows}, indent=2))
    (out / "report.md").write_text(render_report(config, metrics, rows, use_baseline))
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(metrics, indent=2))
    print(f"\nReport written to {out}")


def fmt(v, pct=False):
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else str(v)


def render_report(config, metrics, rows, use_baseline):
    rag, base = metrics["rag"], metrics.get("baseline_no_rag", {})
    lines = [
        "# Evaluation Report", "",
        f"*Run:* {config['timestamp']} · *Provider:* {config['provider']} · *Model:* {config['generation_model']} · "
        f"*Embeddings:* {config['embedding_model']} ({config['embedding_dimensions']}d)", "",
        f"*Chunking:* {config['chunk_size']} chars / {config['chunk_overlap']} overlap · *Top-K:* {config['top_k']} · "
        f"*Threshold:* {config['relevance_threshold']} · *Prompt:* {config['prompt_version']} · "
        f"*LLM judge:* {'on' if config['llm_judge'] else 'off'}", "",
        *(["> **Offline smoke run** (fake provider): numbers only verify the harness and are not a quality measurement.", ""] if config["provider"] == "fake" else []),
        "## Summary", "",
        "| Metric | RAG chatbot | Baseline (no RAG) |",
        "|---|---|---|",
        f"| Retrieval relevance (hit rate) | {fmt(rag['retrieval_relevance_hit_rate'], True)} | — |",
        f"| Context precision | {fmt(rag['context_precision'], True)} | — |",
        f"| Answer correctness (keyword) | {fmt(rag['answer_correctness'], True)} | {fmt(base.get('answer_correctness'), True)} |",
        f"| Groundedness | {fmt(rag['groundedness'], True)} | {fmt(base.get('groundedness'), True)} |",
        f"| Hallucination rate | {fmt(rag['hallucination_rate'], True)} | {fmt(base.get('hallucination_rate'), True)} |",
        f"| False fallback rate (answerable) | {fmt(rag['false_fallback_rate'], True)} | — |",
        f"| Failure handling (unanswerable safe) | {fmt(rag['failure_handling_safe_rate'], True)} | {fmt(base.get('failure_handling_safe_rate'), True)} |",
        f"| Latency mean / p95 (ms) | {rag['latency_ms']['mean']} / {rag['latency_ms']['p95']} | "
        f"{base.get('latency_ms', {}).get('mean', 'n/a')} / {base.get('latency_ms', {}).get('p95', 'n/a')} |",
        "",
        "## Per-question results", "",
        "| ID | Question | Hit | Correct | Grounded | Fallback |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['question']} | error: {r['error'][:60]} | | | |")
            continue
        lines.append(
            f"| {r['id']} | {r['question']} | {fmt(r.get('retrieval_hit'))} | "
            f"{fmt(r.get('rag_correctness'))} | {fmt(r.get('rag_grounded'))} | {r['rag_fallback']} |"
        )
    failures = [r for r in rows if r.get("answerable") and (not r.get("retrieval_hit") or r.get("rag_correctness", 1) < 1)]
    lines += ["", "## Failure cases", ""]
    if not failures:
        lines.append("None on this question set.")
    for r in failures:
        lines += [f"**{r['id']} — {r['question']}**", "", f"> {r.get('rag_answer', '')[:500]}", ""]
    if use_baseline:
        lines += ["", "*The baseline is a direct Gemini chat without retrieval, evaluated on the same question set "
                  "(Proposal §5.3). Its groundedness is judged against the reference document.*"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
