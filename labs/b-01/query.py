#!/usr/bin/env python3
"""Embed one question and run the handout's step-three query: the five nearest chunks, with the
similarity beside each, so the SQL in the handout has a way to be run without writing the embedding
call yourself.

    python query.py --question 9                       a number from questions.yaml
    python query.py --text "what does V-2231 need"     a question of your own
    python query.py --question 9 --table chunks_fixed_300 --k 10

It is the same query measure.py runs for every question, on one question, printed in full. Read
the top hit and the rank of the document you expected; that is what the deliberate failure asks
you to look at.
"""

from __future__ import annotations

import argparse
import sys

import retrieval as r


def main() -> int:
    parser = argparse.ArgumentParser(description="The five nearest chunks for one question.")
    parser.add_argument("--question", type=int, help="a number from the b-01 questions.yaml")
    parser.add_argument("--text", help="a question of your own")
    parser.add_argument("--table", default="chunks")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    if args.question:
        questions = {int(q["id"]): q["text"] for q in r.load_questions(r.CORPUS / "questions.yaml")}
        if args.question not in questions:
            parser.error(f"no question {args.question}; there are {min(questions)} to {max(questions)}")
        question = questions[args.question]
    elif args.text:
        question = args.text
    else:
        parser.error("say --question N or --text '...'")

    vectors, model = r.embed([question])
    print(f"question: {question}\nembedded with {model}, {len(vectors[0])} dimensions\n")
    with r.connect() as conn:
        rows = conn.execute(
            f"""select doc_id, chunk_no, heading, 1 - (embedding <=> %s::vector) as similarity
                from {args.table} order by embedding <=> %s::vector limit %s""",
            (r.vector_literal(vectors[0]), r.vector_literal(vectors[0]), args.k),
        ).fetchall()
    print(f"{'rank':>4}  {'doc_id':<14} {'chunk':>5}  {'similarity':>10}  heading")
    for rank, (doc_id, chunk_no, heading, similarity) in enumerate(rows, start=1):
        print(f"{rank:>4}  {doc_id:<14} {chunk_no:>5}  {similarity:>10.2f}  {heading or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
