#!/usr/bin/env python3
"""The naive pipeline: retrieve the nearest five chunks, stuff them into the prompt, generate.

    python naive.py --question 9      V-2231: answers from a valve maintenance page
    python naive.py --question 11     the lead pipe subsidy: invents a procedure, with a citation

No coverage check, no citation contract, no verifier. It asks the model to cite the document it
used, and the model does, which is what makes the second run worth reading twice: the document id
beside the invented procedure is real, and retrieval really did return it. Nothing errors.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import requests
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "index-the-manuals"))
import retrieval as r  # noqa: E402

CONFIG = yaml.safe_load((pathlib.Path(__file__).resolve().parent / "config.yaml").read_text())
QUESTIONS = r.REPO / "labs" / "corpus" / "ground-the-answer" / "questions.yaml"


def passages(conn, table: str, question: str, k: int) -> list[dict]:
    [embedding], _model = r.embed([question])
    rows = conn.execute(
        f"""select doc_id, doc_version, chunk_no, heading, body, superseded_by,
                   1 - (embedding <=> %s::vector) as similarity
            from {table} order by embedding <=> %s::vector limit %s""",
        (r.vector_literal(embedding), r.vector_literal(embedding), k),
    ).fetchall()
    return [{"id": f"{row[0]} v{row[1]}#{row[2]}", "doc_id": row[0], "version": row[1], "chunk_no": row[2],
             "heading": row[3], "body": row[4], "superseded_by": row[5], "similarity": float(row[6])}
            for row in rows]


def ask(messages: list[dict], model: str | None = None, response_format: dict | None = None) -> str:
    body = {"model": model or CONFIG["model"]["name"], "messages": messages,
            "temperature": CONFIG["model"]["temperature"]}
    if response_format:
        body["response_format"] = response_format
    response = requests.post(f"{r.MODELS}/v1/chat/completions",
                             headers={"Authorization": f"Bearer {r.MODEL_KEY}"}, json=body, timeout=300)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""


def question_text(number: int) -> str:
    return next(q["text"] for q in r.load_questions(QUESTIONS) if int(q["id"]) == number)


def naive_answer(conn, question: str) -> tuple[str, list[dict]]:
    found = passages(conn, CONFIG["retrieval"]["table"], question, CONFIG["retrieval"]["k"])
    context = "\n\n".join(f"[{p['id']}] {p['heading'] or ''}\n{p['body']}" for p in found)
    prompt = (
        "You are the Aquaflux manual assistant, answering a field technician. Answer the question "
        "from the passages below, in two or three sentences, as a procedure the technician can "
        "follow. End with the id of the passage you used, in square brackets.\n\n"
        f"Passages:\n{context}\n\nQuestion: {question}"
    )
    return ask([{"role": "user", "content": prompt}]), found


def main() -> int:
    parser = argparse.ArgumentParser(description="The naive retrieve, stuff, generate pipeline.")
    parser.add_argument("--question", type=int, required=True)
    args = parser.parse_args()
    question = question_text(args.question)
    with r.connect() as conn:
        answer, found = naive_answer(conn, question)
    print(f"question: {question}\nretrieval: vector, k={CONFIG['retrieval']['k']}")
    for i, p in enumerate(found, 1):
        print(f"  {i}. {p['id']:<20} {(p['heading'] or ''):<44} {p['similarity']:.2f}")
    print(f"answer:\n  {answer}\nchecks run: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
