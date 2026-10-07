#!/usr/bin/env python3
"""Score the answering step over the eleven questions: retrieval, faithfulness, refusal.

    python score.py                 all eleven questions, three numbers
    python score.py --calibrate     the judge against the three hand-scored labels in labels.yaml

Three numbers, kept apart because they fail apart:

  recall at five      did a chunk of the answering document reach the top five, vector and hybrid
  faithfulness        for every claim the step returned, a second model call judges whether the
                      cited passage supports it. A judge is a model too, which is why labels.yaml
                      exists and why --calibrate is a step in the lab and not an afterthought
  refusal             did the step refuse exactly the question the corpus cannot answer

Every call goes through the model gateway with your key, so the gateway's spend log tells you
what this golden set cost. The handout has you read it at the end.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "index-the-manuals"))
import retrieval as r  # noqa: E402

import hybrid  # noqa: E402
from answer import answer  # noqa: E402
from naive import CONFIG, ask  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
CORPUS = r.REPO / "labs" / "corpus" / "ground-the-answer"

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["supported", "why"],
    "additionalProperties": False,
}


def judge(claim: str, passage_text: str) -> tuple[bool, str]:
    """Does the passage support the claim? A model's opinion, in a fixed shape."""
    prompt = (
        "You are checking a manual assistant's answer against its source. Below is one passage "
        "and one claim that cites it. Say whether the passage supports the claim: every fact in "
        "the claim, including any number, must be stated in the passage. Paraphrase is fine; a "
        "number or a step the passage does not state is not.\n\n"
        f"Passage:\n{passage_text}\n\nClaim:\n{claim}\n\n"
        'Return JSON of the form {"supported": true or false, "why": "one sentence"}.'
    )
    raw = ask([{"role": "user", "content": prompt}], model=CONFIG["model"]["judge"],
              response_format={"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": VERDICT_SCHEMA}})
    try:
        data = json.loads(raw)
        return bool(data["supported"]), str(data.get("why", ""))
    except (json.JSONDecodeError, KeyError):
        return False, f"unparseable verdict: {raw[:100]}"


def recall(conn, table: str, question: str, expected: list[str], k: int) -> tuple[float, float]:
    [embedding], _ = r.embed([question])
    vector_hits = {row[0] for row in conn.execute(
        f"select doc_id from {table} order by embedding <=> %s::vector limit %s", (r.vector_literal(embedding), k))}
    hybrid_hits = {doc for doc, *_ in hybrid.search(conn, table, question, k)}
    return (1.0 if any(d in vector_hits for d in expected) else 0.0,
            1.0 if any(d in hybrid_hits for d in expected) else 0.0)


def calibrate() -> int:
    labels = yaml.safe_load((CORPUS / "labels.yaml").read_text())["labels"]
    agree = total = 0
    print(f"{'q':>2}  {'hand':<5} {'judge':<5}  claim")
    for label in labels:
        for claim in label["claims"]:
            verdict, why = judge(claim["text"], claim["passage_text"])
            hand = bool(claim["supported"])
            total += 1
            agree += int(verdict == hand)
            mark = "" if verdict == hand else "   <- disagree: " + why[:80]
            print(f"{label['question']:>2}  {str(hand):<5} {str(verdict):<5}  {claim['text'][:60]}{mark}")
    print(f"\njudge agrees with the hand labels on {agree} of {total} claims "
          f"({(total - agree) / max(total, 1):.0%} disagreement)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Score retrieval, faithfulness and refusal over the golden set.")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.calibrate:
        return calibrate()

    questions = r.load_questions(CORPUS / "questions.yaml")
    relevance = r.load_relevance(CORPUS / "relevance.yaml")
    table = CONFIG["retrieval"]["table"]
    rows = []
    with r.connect() as conn:
        for q in questions:
            qid = int(q["id"])
            expected = relevance.get(qid)
            v_recall, h_recall = recall(conn, table, q["text"], expected, args.k) if expected else (None, None)
            result = answer(conn, q["text"])
            supported = 0
            verdicts = []
            if not result["refused"]:
                by_id = {p["id"]: p for p in result["passages"]}
                for claim in result["claims"]:
                    ok, why = judge(claim["text"], by_id[claim["cited"]]["body"])
                    verdicts.append({"claim": claim["text"], "cited": claim["cited"], "supported": ok, "why": why})
                    supported += int(ok)
            rows.append({"id": qid, "question": q["text"], "expected": expected, "vector": v_recall, "hybrid": h_recall,
                         "refused": result["refused"], "claims": len(result["claims"]),
                         "rejected": len(result["rejected"]), "supported": supported, "verdicts": verdicts,
                         "should_refuse": expected is None})

    if args.json:
        print(json.dumps(rows, indent=2)); return 0

    print(f"{'q':>2}  {'vector':>6}  {'hybrid':>6}  {'claims':>6}  {'faithful':>8}  {'refused':>7}  question")
    for row in rows:
        v = "-" if row["vector"] is None else f"{row['vector']:.1f}"
        h = "-" if row["hybrid"] is None else f"{row['hybrid']:.1f}"
        f = "-" if row["refused"] or not row["claims"] else f"{row['supported']}/{row['claims']}"
        print(f"{row['id']:>2}  {v:>6}  {h:>6}  {row['claims']:>6}  {f:>8}  {str(row['refused']):>7}  {row['question'][:50]}")
    scored = [row for row in rows if row["vector"] is not None]
    claims = sum(row["claims"] for row in rows)
    supported = sum(row["supported"] for row in rows)
    correct_refusals = sum(1 for row in rows if row["refused"] == row["should_refuse"])
    print(f"\nrecall@{args.k}  vector {sum(r_['vector'] for r_ in scored) / len(scored):.2f}   "
          f"hybrid {sum(r_['hybrid'] for r_ in scored) / len(scored):.2f}   over {len(scored)} questions")
    print(f"faithfulness  {supported}/{claims} claims judged supported by their cited passage")
    print(f"refusal       {correct_refusals}/{len(rows)} questions refused exactly when they should be "
          f"(eleven should be, the rest should not)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
