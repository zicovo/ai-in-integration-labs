#!/usr/bin/env python3
"""Recall at k over the ten questions, with the top hit shown, so a table is read and not a feeling.

    python measure.py                                  vector search on `chunks`, k=5
    python measure.py --table chunks_fixed_300         another table, same questions
    python measure.py --retriever hybrid               ground-the-assistant: vector and lexical, fused
    python measure.py --k 3 --ef-search 10             index-the-manuals completion tier's trade-off

A question is a hit when any chunk of a document named in relevance.yaml is in the top k. The
top hit is printed for every question, because recall at five can read 1.0 while the model
would have answered from the wrong page: the asset sheet scraping into fifth place is the case
the handout tells you to read.

Question eleven (ground-the-assistant) has no relevance entry and is skipped here; score.py is where it counts.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

import retrieval as r

B02 = r.REPO / "labs" / "corpus" / "ground-the-assistant"


def vector_search(conn, table: str, question: str, limit: int) -> list[tuple[str, int, str | None, float]]:
    [vector], _model = r.embed([question])
    rows = conn.execute(
        f"""select doc_id, chunk_no, heading, 1 - (embedding <=> %s::vector) as similarity
            from {table} order by embedding <=> %s::vector limit %s""",
        (r.vector_literal(vector), r.vector_literal(vector), limit),
    ).fetchall()
    return [(row[0], row[1], row[2], float(row[3])) for row in rows]


def hybrid_search(conn, table: str, question: str, limit: int):
    """ground-the-assistant's retriever: reciprocal rank fusion of the vector ranking and the lexical one."""
    sys.path.insert(0, str(r.REPO / "labs" / "ground-the-assistant"))
    import hybrid  # noqa: E402  the file the ground-the-assistant handout has you read

    return hybrid.search(conn, table, question, limit)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall at k over the test questions.")
    parser.add_argument("--table", default="chunks")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--retriever", choices=["vector", "hybrid"], default="vector")
    parser.add_argument("--ef-search", type=int, default=None, help="set hnsw.ef_search for this session")
    parser.add_argument("--questions", default=None, help="a questions.yaml (default: the index-the-manuals set)")
    parser.add_argument("--relevance", default=None)
    args = parser.parse_args()

    corpus = r.CORPUS
    questions = r.load_questions(pathlib.Path(args.questions) if args.questions else corpus / "questions.yaml")
    relevance = r.load_relevance(pathlib.Path(args.relevance) if args.relevance else corpus / "relevance.yaml")
    search = vector_search if args.retriever == "vector" else hybrid_search

    hits = 0
    scored = 0
    print(f"{'q':>2}  {'recall@' + str(args.k):>9}  {'top hit':<40}  question")
    with r.connect() as conn:
        if args.ef_search is not None:
            conn.execute(f"set hnsw.ef_search = {int(args.ef_search)}")
        started = time.monotonic()
        for question in questions:
            expected = relevance.get(int(question["id"]))
            if not expected:
                continue
            results = search(conn, args.table, question["text"], args.k)
            found = {doc_id for doc_id, *_ in results}
            hit = any(doc in found for doc in expected)
            top = results[0] if results else ("-", 0, None, 0.0)
            top_label = f"{top[0]}#{top[1]} {top[2] or ''}".strip()
            marker = "" if hit else "  <- expected " + ", ".join(expected)
            print(f"{question['id']:>2}  {1.0 if hit else 0.0:>9.1f}  {top_label[:40]:<40}  {question['text'][:48]}{marker}")
            hits += int(hit)
            scored += 1
        elapsed = time.monotonic() - started
    print(f"\naverage recall@{args.k}: {hits / max(scored, 1):.2f} over {scored} questions, "
          f"{args.retriever} on {args.table}, {elapsed / max(scored, 1) * 1000:.0f} ms per question")
    return 0


if __name__ == "__main__":
    sys.exit(main())
