#!/usr/bin/env python3
"""Two retrievers over the same table, fused into one ranking. Read it before you run it.

    python hybrid.py --question 9        both rankings and the fused one, for one question
    python hybrid.py --text "..."         the same for a question of your own

The vector retriever is index-the-manuals's. The lexical retriever is PostgreSQL's own full text search, in
the same database, ranked with ts_rank_cd, plus one thing that matters for identifiers: any chunk
that contains a code from the question verbatim (V-2231, T2, WO 71822) goes to the top of the
lexical list. Full text ranking has no notion of a rare term, because it uses no global
information; the study text says so, and it means the string V-2231 counts for no more than the
word "next". Exact match on the code is the retriever index-the-manuals told you would have found the asset
sheet, and it is one `ilike`.

Fusion is reciprocal rank fusion: each ranking contributes 1 / (k + position) for every candidate
it holds, and the sums are sorted. It needs no score normalisation, which is why it is the usual
choice for fusing a similarity with a rank that cannot be normalised.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "index-the-manuals"))
import retrieval as r  # noqa: E402  index-the-manuals's corpus, embedding and database helpers

IDENTIFIER = re.compile(r"\b(?:[A-Z]{1,4}-\d{2,6}|[A-Z]\d{1,2}|WO \d{4,6})\b")


def vector(conn, question: str, limit: int = 20, table: str = "chunks") -> list[tuple[str, int]]:
    [embedding], _model = r.embed([question])
    rows = conn.execute(
        f"select doc_id, chunk_no from {table} order by embedding <=> %s::vector limit %s",
        (r.vector_literal(embedding), limit),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def identifiers(question: str) -> list[str]:
    """Codes in the question: asset codes like V-2231, tariff codes like T2, work orders."""
    return IDENTIFIER.findall(question)


def lexical(conn, question: str, limit: int = 20, table: str = "chunks") -> list[tuple[str, int]]:
    """Full text search, with exact identifier matches first.

    The terms are OR-ed: `plainto_tsquery` ANDs them, and a seven word question rarely has all
    seven lexemes in one chunk. Cover density ranking then prefers chunks holding more of the
    terms, closer together.
    """
    ranked: list[tuple[str, int]] = []
    for code in identifiers(question):
        rows = conn.execute(
            f"select doc_id, chunk_no from {table} where body ilike %s or heading ilike %s order by doc_id, chunk_no",
            (f"%{code}%", f"%{code}%"),
        ).fetchall()
        ranked.extend((row[0], row[1]) for row in rows if (row[0], row[1]) not in ranked)

    tsquery = conn.execute("select plainto_tsquery('english', %s)::text", (question,)).fetchone()[0]
    if tsquery:
        or_query = tsquery.replace(" & ", " | ")
        rows = conn.execute(
            f"""select doc_id, chunk_no,
                       ts_rank_cd(to_tsvector('english', coalesce(heading,'') || ' ' || body),
                                  to_tsquery('english', %s)) as rank
                from {table}
                where to_tsvector('english', coalesce(heading,'') || ' ' || body)
                      @@ to_tsquery('english', %s)
                order by rank desc limit %s""",
            (or_query, or_query, limit),
        ).fetchall()
        ranked.extend((row[0], row[1]) for row in rows if (row[0], row[1]) not in ranked)
    return ranked[:limit]


def fuse(rankings: list[list[tuple[str, int]]], k: int = 60) -> list[tuple[tuple[str, int], float]]:
    """Reciprocal rank fusion. Returns (key, fused score), best first."""
    scores: dict[tuple[str, int], float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def search(conn, table: str, question: str, limit: int) -> list[tuple[str, int, str | None, float]]:
    """measure.py's contract: (doc_id, chunk_no, heading, score) for the top `limit`, fused."""
    fused = fuse([vector(conn, question, table=table), lexical(conn, question, table=table)])
    out = []
    for (doc_id, chunk_no), score in fused[:limit]:
        heading = conn.execute(f"select heading from {table} where doc_id = %s and chunk_no = %s",
                               (doc_id, chunk_no)).fetchone()[0]
        out.append((doc_id, chunk_no, heading, score))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Show both rankings and the fused one for a question.")
    parser.add_argument("--question", type=int, help="a number from the ground-the-answer questions.yaml")
    parser.add_argument("--text", help="a question of your own")
    parser.add_argument("--table", default="chunks")
    args = parser.parse_args()
    if args.question:
        questions = r.load_questions(r.REPO / "labs" / "corpus" / "ground-the-answer" / "questions.yaml")
        text = next(q["text"] for q in questions if int(q["id"]) == args.question)
    elif args.text:
        text = args.text
    else:
        parser.error("say --question N or --text '...'")

    with r.connect() as conn:
        v = vector(conn, text, table=args.table)
        lex = lexical(conn, text, table=args.table)
        fused = fuse([v, lex])
    print(f"question: {text}")
    print(f"identifiers: {identifiers(text) or 'none'}\n")
    print(f"{'#':>2}  {'vector':<22}  {'lexical':<22}  {'fused':<22}")
    for i in range(10):
        cell = lambda ranking: f"{ranking[i][0]}#{ranking[i][1]}" if i < len(ranking) else ""  # noqa: E731
        fused_cell = f"{fused[i][0][0]}#{fused[i][0][1]} {fused[i][1]:.4f}" if i < len(fused) else ""
        print(f"{i + 1:>2}  {cell(v):<22}  {cell(lex):<22}  {fused_cell:<22}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
