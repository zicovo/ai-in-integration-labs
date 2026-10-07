#!/usr/bin/env python3
"""The grounded answering step. Three things, in this order, and the order matters.

    python answer.py --question 9       right document, claims cited
    python answer.py --question 11      refusal, with leads, model not called
    python answer.py --question 11 --no-coverage-check --no-verifier    what the checks were for

1. Coverage check, before the model. On evidence the model never sees: the best vector similarity
   among the fused candidates, and whether a code in the question was matched exactly. Below
   the threshold in config.yaml, the step returns the fixed refusal with the nearest documents as
   leads, and the model is not called.
2. The citation contract. The model is given the passages, each with its document id, version
   and text, and an output schema: a list of claims, each with `text` and `cited` naming one
   passage id. Nothing else is accepted.
3. The verifier, after the model. Every claim's `cited` must be one of the passages supplied,
   and that passage's document must be current. A claim that fails is dropped and the answer is
   marked incomplete rather than sent as written. The rejection is printed, not hidden.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "index-the-manuals"))
import retrieval as r  # noqa: E402

import hybrid  # noqa: E402
from naive import CONFIG, ask, question_text  # noqa: E402

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "cited": {"type": "string"}},
                "required": ["text", "cited"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


def retrieve(conn, question: str) -> tuple[list[dict], dict]:
    """The fused top k as passages, plus the coverage evidence the check reads."""
    cfg = CONFIG["retrieval"]
    table = cfg["table"]
    [embedding], _model = r.embed([question])
    vector_rows = conn.execute(
        f"""select doc_id, chunk_no, 1 - (embedding <=> %s::vector) from {table}
            order by embedding <=> %s::vector limit %s""",
        (r.vector_literal(embedding), r.vector_literal(embedding), cfg["candidates"]),
    ).fetchall()
    similarity = {(row[0], row[1]): float(row[2]) for row in vector_rows}
    vector_ranking = [(row[0], row[1]) for row in vector_rows]
    lexical_ranking = hybrid.lexical(conn, question, cfg["candidates"], table)
    codes = hybrid.identifiers(question)
    matched_codes = [code for code in codes if any(
        conn.execute(f"select 1 from {table} where doc_id = %s and chunk_no = %s and (body ilike %s or heading ilike %s)",
                     (d, c, f"%{code}%", f"%{code}%")).fetchone() for d, c in lexical_ranking[:5])]
    fused = hybrid.fuse([vector_ranking, lexical_ranking], cfg["rrf_k"])[:cfg["k"]]

    passages = []
    for (doc_id, chunk_no), score in fused:
        row = conn.execute(
            f"select doc_version, heading, body, superseded_by, valid_from from {table} where doc_id = %s and chunk_no = %s",
            (doc_id, chunk_no)).fetchone()
        passages.append({"id": f"{doc_id} v{row[0]}#{chunk_no}", "doc_id": doc_id, "version": row[0],
                         "chunk_no": chunk_no, "heading": row[1], "body": row[2], "superseded_by": row[3],
                         "valid_from": str(row[4]), "fused": score,
                         "similarity": similarity.get((doc_id, chunk_no))})
    evidence = {
        "best_similarity": max((p["similarity"] for p in passages if p["similarity"] is not None), default=0.0),
        "identifiers": codes,
        "identifier_matched": bool(matched_codes),
        "candidate_documents": [doc_id for (doc_id, _), _ in
                                hybrid.fuse([vector_ranking, lexical_ranking], cfg["rrf_k"])],
    }
    return passages, evidence


def covered(evidence: dict) -> tuple[bool, str]:
    cfg = CONFIG["coverage"]
    if evidence["identifier_matched"] and cfg.get("accept_identifier_match", True):
        return True, f"a code from the question was matched exactly: {', '.join(evidence['identifiers'])}"
    if evidence["best_similarity"] >= cfg["min_similarity"]:
        return True, f"best similarity {evidence['best_similarity']:.2f} is at least {cfg['min_similarity']}"
    return False, (f"best similarity {evidence['best_similarity']:.2f} is below {cfg['min_similarity']} "
                   f"and no code from the question was matched")


def generate(question: str, passages: list[dict]) -> list[dict]:
    """The citation contract: claims, each naming the passage it rests on."""
    context = "\n\n".join(f"passage id: {p['id']}\nheading: {p['heading'] or ''}\n{p['body']}" for p in passages)
    prompt = (
        "You are the Aquaflux manual assistant, answering a field technician from the passages "
        "below and from nothing else. Write the answer as a list of short claims. Each claim is one "
        "sentence the technician can act on, and `cited` is the id of the one passage that states "
        "it, copied exactly. Do not write a claim that no passage states. If the passages do not "
        "answer the question, return an empty list of claims.\n\n"
        f"Passages:\n{context}\n\nQuestion: {question}\n\n"
        'Return JSON of the form {"claims": [{"text": "...", "cited": "<passage id>"}]}.'
    )
    raw = ask([{"role": "user", "content": prompt}],
              response_format={"type": "json_schema", "json_schema": {"name": "claims", "strict": True, "schema": CLAIMS_SCHEMA}})
    try:
        return json.loads(raw).get("claims", [])
    except json.JSONDecodeError:
        return [{"text": raw.strip(), "cited": ""}]


def verify(claims: list[dict], passages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep the claims whose citation is a supplied, current passage. Return (kept, rejected)."""
    supplied = {p["id"]: p for p in passages}
    kept, rejected = [], []
    for claim in claims:
        passage = supplied.get(claim.get("cited", ""))
        if passage is None:
            rejected.append({**claim, "reason": "cited passage was not among those supplied"})
        elif passage["superseded_by"]:
            rejected.append({**claim, "reason": f"cited passage is superseded by {passage['superseded_by']}"})
        else:
            kept.append(claim)
    return kept, rejected


def answer(conn, question: str, coverage_check: bool = True, verifier: bool = True) -> dict:
    passages, evidence = retrieve(conn, question)
    ok, reason = covered(evidence)
    if coverage_check and not ok:
        # The leads are documents, not chunks: the k passages may all come from one document, so
        # walk the fused candidates until enough distinct documents are named.
        leads = []
        for doc_id in evidence["candidate_documents"]:
            if doc_id not in leads:
                leads.append(doc_id)
            if len(leads) >= CONFIG["coverage"]["leads"]:
                break
        return {"question": question, "refused": True, "reason": reason, "model_called": False,
                "leads": leads, "refusal": CONFIG["refusal"].strip(),
                "claims": [], "rejected": [], "passages": passages, "evidence": evidence}
    claims = generate(question, passages)
    kept, rejected = verify(claims, passages) if verifier else (claims, [])
    return {"question": question, "refused": False, "covered": ok, "reason": reason, "model_called": True,
            "coverage_check": coverage_check, "verifier": verifier,
            "claims": kept, "rejected": rejected, "incomplete": bool(rejected) or not kept,
            "passages": passages, "evidence": evidence}


def main() -> int:
    parser = argparse.ArgumentParser(description="The grounded answering step.")
    parser.add_argument("--question", type=int)
    parser.add_argument("--text")
    parser.add_argument("--no-coverage-check", action="store_true")
    parser.add_argument("--no-verifier", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    question = question_text(args.question) if args.question else args.text
    if not question:
        parser.error("say --question N or --text '...'")
    with r.connect() as conn:
        result = answer(conn, question, not args.no_coverage_check, not args.no_verifier)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0
    print(f"question: {question}")
    if result["refused"]:
        print(f"coverage: refused: {result['reason']}")
    elif not result.get("coverage_check", True) and not result.get("covered", True):
        print(f"coverage: check skipped (--no-coverage-check). It would have refused: {result['reason']}")
    else:
        print(f"coverage: covered: {result['reason']}")
    print(f"model called: {result['model_called']}")
    if result["refused"]:
        print(f"refusal: {result['refusal']}\nleads: {', '.join(result['leads'])}")
        return 0
    if not result.get("verifier", True):
        print("verifier: skipped (--no-verifier), so every claim below is printed as the model wrote it")
    if not result["claims"] and not result["rejected"]:
        print("  the model returned no claims: given these passages, it declined to answer")
    for claim in result["claims"]:
        print(f"  claim: {claim['text']}\n         [{claim['cited']}]")
    for claim in result["rejected"]:
        print(f"  REJECTED: {claim['text']}\n         cited [{claim.get('cited')}]: {claim['reason']}")
    if result["rejected"]:
        print(f"answer marked incomplete: {len(result['rejected'])} claim(s) rejected by the verifier")
    elif result["incomplete"]:
        print("answer marked incomplete: there are no claims to return")
    return 0


if __name__ == "__main__":
    sys.exit(main())
