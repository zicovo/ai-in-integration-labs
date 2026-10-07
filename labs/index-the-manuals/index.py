#!/usr/bin/env python3
"""Index the Aquaflux corpus into PostgreSQL with pgvector. The worked tier's reference.

    python index.py                          twenty documents, split on headings, into `chunks`
    python index.py --rule fixed-300         fixed-size chunks instead, into `chunks_fixed_300`
    python index.py --table mine             a table of your own, created if it does not exist
    python index.py --include-superseded     also index superseded/, to see a stale page found
    python index.py --replace                empty the table first. Without it, a table that already
                                             holds rows is left alone and the script says so

Read it before you run it. It splits each document into chunks (retrieval.py has the two rules),
embeds each chunk through the model gateway, and inserts one row per chunk with the model that
produced the vector and the rule that cut the chunk, because a vector is only meaningful together
with both. Re-indexing with another rule or another model goes into another table for the same
reason: mixing them in one table would make the recall table below meaningless.

The schema is the one the handout prints. The table is created if it does not exist, so the
smoke test can load a reference index for ground-the-answer; in the worked tier you create it yourself first,
with the vector length your smoke test printed.
"""

from __future__ import annotations

import argparse
import sys
import time

import retrieval as r


def ensure_table(conn, table: str, dims: int) -> None:
    conn.execute("create extension if not exists vector")
    conn.execute(f"""
        create table if not exists {table} (
          id            bigserial primary key,
          doc_id        text not null,
          doc_version   int  not null,
          chunk_no      int  not null,
          heading       text,
          body          text not null,
          department    text not null,
          valid_from    date,
          superseded_by text,
          model         text not null,
          chunk_rule    text not null,
          embedding     vector({dims}) not null
        )
    """)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index the corpus into PostgreSQL with pgvector.")
    parser.add_argument("--rule", choices=sorted(r.RULES), default="headings")
    parser.add_argument("--table", default=None, help="default: chunks, or chunks_<rule> for another rule")
    parser.add_argument("--model", default=r.EMBED_MODEL, help="the gateway's model name (default aquaflux-embed)")
    parser.add_argument("--include-superseded", action="store_true")
    parser.add_argument("--replace", action="store_true", help="empty the table first")
    args = parser.parse_args()
    table = args.table or ("chunks" if args.rule == "headings" else "chunks_" + args.rule.replace("-", "_"))

    documents = r.load_corpus(include_superseded=args.include_superseded)
    chunks = [chunk for doc in documents for chunk in r.RULES[args.rule](doc)]
    print(f"{len(documents)} documents, {len(chunks)} chunks with rule {args.rule}")

    started = time.monotonic()
    vectors, model = r.embed([chunk.text_to_embed() for chunk in chunks], args.model)
    dims = len(vectors[0])
    print(f"embedded with {model}, {dims} dimensions, in {time.monotonic() - started:.1f}s")

    with r.connect() as conn:
        ensure_table(conn, table, dims)
        existing = conn.execute(f"select count(*) from {table}").fetchone()[0]
        if args.replace:
            conn.execute(f"truncate {table}")
        elif existing:
            # Adding a second copy of every chunk to a table that already holds one would put
            # duplicates in every top five and make the recall table meaningless, and it would
            # do so silently. Seen when a table was left by an earlier session; refuse instead.
            print(f"{table} already holds {existing} rows from an earlier run, and this would add "
                  f"{len(chunks)} more on top of them.\n"
                  f"  start again with:   python index.py --replace"
                  + (f" --rule {args.rule}" if args.rule != "headings" else "")
                  + (f" --table {table}" if args.table else "") + "\n"
                  f"  or keep them as they are and go on to:   python measure.py"
                  + (f" --table {table}" if table != "chunks" else ""), file=sys.stderr)
            return 1
        with conn.cursor() as cur:
            for chunk, vector in zip(chunks, vectors):
                cur.execute(
                    f"""insert into {table} (doc_id, doc_version, chunk_no, heading, body, department,
                                              valid_from, superseded_by, model, chunk_rule, embedding)
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)""",
                    (chunk.doc.id, chunk.doc.version, chunk.chunk_no, chunk.heading, chunk.body,
                     chunk.doc.department, chunk.doc.valid_from, chunk.doc.superseded_by,
                     model, args.rule, r.vector_literal(vector)),
                )
        conn.execute(f"create index if not exists {table}_embedding_idx on {table} using hnsw (embedding vector_cosine_ops)")
        # ground-the-answer's lexical retriever reads this. A generated column with a GIN index, so the full
        # text query in the handout is fast and the learner does not have to build it (the
        # instructor note in ground-the-answer asks for exactly that).
        conn.execute(f"""
            alter table {table} add column if not exists tsv tsvector
              generated always as (to_tsvector('english', coalesce(heading, '') || ' ' || body)) stored
        """)
        conn.execute(f"create index if not exists {table}_tsv_idx on {table} using gin (tsv)")
        count = conn.execute(f"select count(*) from {table}").fetchone()[0]
        conn.commit()
    print(f"{table}: {count} rows, model {model}, rule {args.rule}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
