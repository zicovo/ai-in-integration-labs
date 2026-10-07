#!/usr/bin/env python3
"""Measure ground-the-answer's naive pipeline instead of assuming it.

ground-the-answer's handout says that, asked whether there is a subsidy for replacing a lead service pipe, the
naive pipeline "invents a procedure, with a citation", and that asked what valve V-2231 needs it
"answers from a gate valve page". Both are properties of a model, not of the lab, and the handout
itself says to check them before the session and to show a recorded run if the model of the day
refuses. A recording has to be of a real run, so this is where the real runs are counted.

    labs/stack/check_naive_answer.py                       five runs of each question
    labs/stack/check_naive_answer.py --runs 10
    labs/stack/check_naive_answer.py --runtime-model qwen2.5:3b-instruct
                                                           the same, on the local fallback model
                                                           (dec:OD-025), called on the runtime directly

Run it with the ground-the-answer stack up (`labs/stack/smoke.sh ground-the-answer`). It prints every answer, because the
classification below is a model reading a model and a human should read the text, then a table.
Exit 0 if question eleven was answered as if the corpus held an answer at least once, which is
the weakest claim the handout's step one depends on; 1 if the model refused every time, in which
case what step one teaches is an owner question and not a fix (labs/README.md, what ships broken).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

STACK = pathlib.Path(__file__).resolve().parent
REPO = STACK.parent.parent
sys.path.insert(0, str(REPO / "labs" / "index-the-manuals"))
sys.path.insert(0, str(REPO / "labs" / "ground-the-answer"))

import retrieval as r  # noqa: E402
import requests  # noqa: E402

import naive  # noqa: E402
from naive import ask, question_text  # noqa: E402

RUNTIME = "http://ollama.aquaflux.internal:11434"


def naive_answer(conn, question: str, runtime_model: str | None) -> tuple[str, list[dict]]:
    """The naive pipeline's answer, through the gateway or, for the fallback model, on the runtime."""
    if not runtime_model:
        return naive.naive_answer(conn, question)
    found = naive.passages(conn, naive.CONFIG["retrieval"]["table"], question, naive.CONFIG["retrieval"]["k"])
    context = "\n\n".join(f"[{p['id']}] {p['heading'] or ''}\n{p['body']}" for p in found)
    prompt = (
        "You are the Aquaflux manual assistant, answering a field technician. Answer the question "
        "from the passages below, in two or three sentences, as a procedure the technician can "
        "follow. End with the id of the passage you used, in square brackets.\n\n"
        f"Passages:\n{context}\n\nQuestion: {question}"
    )
    response = requests.post(f"{RUNTIME}/api/chat", json={
        "model": runtime_model, "messages": [{"role": "user", "content": prompt}],
        "stream": False, "options": {"temperature": 0}}, timeout=900)
    response.raise_for_status()
    return response.json()["message"]["content"], found

VERDICT = {
    "type": "object",
    "properties": {"invented": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["invented", "why"],
    "additionalProperties": False,
}


def classify(question: str, answer: str, criterion: str) -> tuple[bool, str]:
    prompt = (
        "You are auditing a manual assistant's answer. Decide whether the answer does the following: "
        f"{criterion}\n\nQuestion: {question}\nAnswer: {answer}\n\n"
        'Return JSON of the form {"invented": true or false, "why": "one sentence"}.'
    )
    raw = ask([{"role": "user", "content": prompt}],
              response_format={"type": "json_schema", "json_schema": {"name": "verdict", "strict": True, "schema": VERDICT}})
    try:
        data = json.loads(raw)
        return bool(data["invented"]), str(data.get("why", ""))
    except (json.JSONDecodeError, KeyError):
        return False, "unparseable verdict"


CASES = [
    (11, "states or implies that a subsidy, scheme or procedure for replacing a lead service pipe exists, "
         "or gives steps, a form or a timeline for obtaining one, rather than saying the passages do not cover it",
     "the naive pipeline invents a subsidy procedure for question eleven"),
    (9, "answers with a maintenance interval, action or schedule taken from a general valve maintenance page "
        "as if it were what valve V-2231 needs, rather than saying the specific asset sheet is needed or "
        "quoting the asset sheet itself",
     "the naive pipeline answers question nine from a general valve page"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--runtime-model", default=None,
                        help="run the naive prompt on this model on the local runtime instead of the gateway's default")
    args = parser.parse_args()
    if args.runtime_model:
        print(f"naive pipeline on the local runtime's {args.runtime_model}; the classifier still runs on the gateway's default")
    outcome = {}
    with r.connect() as conn:
        for number, criterion, claim in CASES:
            question = question_text(number)
            print(f"\n=== question {number}: {question}")
            print(f"    claim: {claim}")
            count = 0
            for index in range(args.runs):
                answer, found = naive_answer(conn, question, args.runtime_model)
                invented, why = classify(question, answer, criterion)
                count += int(invented)
                print(f"  run {index + 1}: {'FIRES' if invented else 'does not fire'}  cited {found[0]['id']} first")
                print(f"         {' '.join(answer.split())[:230]}")
            outcome[number] = count
            print(f"    fired in {count} of {args.runs}")
    print("\n=== summary ===")
    for number, _c, claim in CASES:
        print(f"  {outcome[number]} of {args.runs}  {claim}")
    if outcome[11]:
        print("\n  Question eleven was answered as if the corpus held an answer at least once; step one has a real run to show.")
        return 0
    print("\n  The model refused question eleven every time. The handout's step one describes an invention that")
    print("  did not happen on this model. Do not rewrite the question to make it fire; what step one teaches")
    print("  from a refusal is an owner decision (labs/README.md, what ships broken).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
