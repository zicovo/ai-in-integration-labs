#!/usr/bin/env python3
"""Measure what the model does with c-02's two catalogues instead of assuming it.

c-02's handout (`dec:OD-026`) says that, given the generated twenty-three tool catalogue and a
request to check a meter, the model reaches the generic `create_work_order` and the log line
reads `allow` under `wo-tools-1`; the learner then makes the disconnection call by hand through
the same tool and compares. It also says the key the model invents is not a UUID and that a retry
with a fresh key creates a second work order. Those are properties of a model, not of a lab, and
`labs/README.md` says a claim that has quietly stopped being true is worse than no lab, because
the room runs the exercise, every check is green, and nobody learns what the green meant.

So this runs the lab's own question against both catalogues, several times, and reports what the
model actually did: which write tool it reached, which `type` it filled in, the shape of the key
it sent, and how many work orders each run left on the connection. It is the c-02 counterpart of
`check_seeded_failure.py` and it is on the list to run before every delivery and after any model
change.

    labs/stack/check_tool_choice.py             five runs of each catalogue
    labs/stack/check_tool_choice.py --runs 10
    labs/stack/check_tool_choice.py --only generated
    labs/stack/check_tool_choice.py --step-six   what the negative sentence is worth

It does not decide whether the lab is sound. It prints a table and exits 0 if every generated run
reached `create_work_order`, which is the one claim the handout's log line depends on. A run that
fills `type` with `disconnection` is reported as a bonus, never required: an earlier draft of the
handout depended on it, it never happened, and OD-026 records why the lab no longer does. Read
the table; the exit code is for a smoke test.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys
import urllib.request

STACK = pathlib.Path(__file__).resolve().parent
QUESTION = "the customer on 4471 says their bill doubled, can someone check the meter"

CATALOGUES = {
    "generated": ("labs/c-02/generated", "8851", "wo-tools-1"),
    "curated": ("labs/c-02/curated", "8850", "wo-tools-3"),
}

# c-02's worked tier step six: delete the sentence that says what the tool is not for, ask about
# a leak, and see what moves. The learner is asked to write two sentences on it, so it has to
# actually move.
NEGATIVE_SENTENCE = " Do not use it for leaks, outages or disconnections."
LEAK = ("there is water coming up through the pavement outside number 14 "
        "on connection 4471")
CURATED_SERVER = STACK.parent / "c-02" / "curated" / "server.py"
WOM = "https://wom.aquaflux.internal/v4/work-orders?connection_id=4471"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def reset() -> None:
    """Clear connection 4471, the way `smoke.sh c-02` does before the lab starts.

    Work order 88213 is seeded on that connection for d-04. Leave it there and the agent finds
    a meter check already proposed and stops, which is a true answer to the question and the
    end of the exercise.
    """
    request = urllib.request.Request(WOM, method="DELETE")
    urllib.request.urlopen(request, timeout=20).read()


def orders_left() -> int:
    """How many work orders one run left on connection 4471. Two is the duplicate the lab names."""
    with urllib.request.urlopen(WOM, timeout=20) as response:
        return len(json.loads(response.read()))


def run_once() -> dict:
    reset()
    result = subprocess.run(
        [str(STACK / "ask.sh"), "--json", QUESTION],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()[-300:] or "ask.sh failed", "calls": []}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"unparseable output: {result.stdout[-300:]}", "calls": []}


def summarise(run: dict) -> tuple[str, str | None]:
    """What this run did, in two words: the write tool it reached, and the type it asked for."""
    for call in run.get("calls", []):
        tool = call["tool"]
        if not tool.startswith(("create_", "cancel_", "complete_", "start_", "reopen_")):
            continue
        asked = call.get("arguments", {}).get("type")
        return tool, asked
    return "no write tool", None


def keys_sent(run: dict) -> list[str]:
    """Every idempotency key the model put in a write call, in order.

    The generated tool calls it `idempotency_key` and the curated one `request_id`; the handout
    asks the learner to read the value and notice it is not a UUID, and a second distinct key in
    one run is a retry that made a duplicate.
    """
    keys = []
    for call in run.get("calls", []):
        if not call["tool"].startswith("create_"):
            continue
        arguments = call.get("arguments", {})
        key = arguments.get("idempotency_key") or arguments.get("request_id")
        if key is not None:
            keys.append(str(key))
    return keys


def register(catalogue: str) -> bool:
    directory, port, policy = CATALOGUES[catalogue]
    result = subprocess.run(
        [str(STACK / "register-tool-server.sh"), directory, port, "--policy", policy],
        capture_output=True, text=True, timeout=180, cwd=str(STACK.parent.parent),
    )
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
    return result.returncode == 0


def step_six(runs: int) -> int:
    """Measure what the negative sentence buys, by taking it out and putting it back."""
    original = CURATED_SERVER.read_text()
    if NEGATIVE_SENTENCE not in original:
        print(f"  the sentence is not in {CURATED_SERVER}, so there is nothing to remove")
        return 2

    subprocess.run([str(STACK / "register-tool-server.sh"), "--stop"],
                   capture_output=True, text=True)
    results = {}
    try:
        for label, text in (("with the sentence", original),
                            ("without it", original.replace(NEGATIVE_SENTENCE, ""))):
            CURATED_SERVER.write_text(text)
            if not register("curated"):
                return 2
            print(f"\n=== {label} ===")
            booked = 0
            for index in range(runs):
                reset()
                result = subprocess.run(
                    [str(STACK / "ask.sh"), "--json", LEAK],
                    capture_output=True, text=True, timeout=600,
                )
                try:
                    calls = [c["tool"] for c in json.loads(result.stdout).get("calls", [])]
                except json.JSONDecodeError:
                    calls = ["<unparseable>"]
                if any(c.startswith("create_") for c in calls):
                    booked += 1
                print(f"  run {index + 1}: {calls or 'no tool call'}")
            results[label] = booked
    finally:
        CURATED_SERVER.write_text(original)
        subprocess.run([str(STACK / "register-tool-server.sh"), "labs/c-02/curated", "8850",
                        "--policy", "wo-tools-3"], capture_output=True, text=True,
                       cwd=str(STACK.parent.parent))

    print("\n=== summary ===")
    for label, booked in results.items():
        print(f"  {label:<20} booked a meter check for a leak in {booked} of {runs} runs")
    if results.get("without it", 0) > results.get("with the sentence", 0):
        print("\n  The sentence is doing work. Step six has something to show.")
        return 0
    print("\n  Removing the sentence changed nothing in these runs. Step six asks the learner")
    print("  to write two sentences on what moved, and on this model nothing did. Either run")
    print("  more of them, or say so in the room rather than waiting for it.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--only", choices=sorted(CATALOGUES))
    parser.add_argument("--step-six", action="store_true",
                        help="measure c-02 worked tier step six instead")
    args = parser.parse_args()

    if args.step_six:
        return step_six(args.runs)

    wanted = [args.only] if args.only else list(CATALOGUES)
    findings: dict[str, collections.Counter] = {}
    report: dict[str, tuple[list[str], int]] = {}

    for catalogue in wanted:
        print(f"\n=== {catalogue} ===")
        subprocess.run([str(STACK / "register-tool-server.sh"), "--stop"],
                       capture_output=True, text=True)
        if not register(catalogue):
            print(f"  could not register {catalogue}")
            return 2

        tally: collections.Counter = collections.Counter()
        keys: list[str] = []
        duplicates = 0
        for index in range(args.runs):
            run = run_once()
            if run.get("error"):
                print(f"  run {index + 1}: error: {run['error']}")
                tally["error"] += 1
                continue
            tool, asked = summarise(run)
            decisions = ",".join(sorted({
                str(c.get("status")) for c in run.get("calls", [])
            })) or "-"
            label = f"{tool}({asked})" if asked is not None else tool
            tally[label] += 1
            sent = keys_sent(run)
            keys.extend(sent)
            left = orders_left()
            if left > 1:
                duplicates += 1
            print(f"  run {index + 1}: {label:<44} http {decisions:<8} "
                  f"orders {left}  keys {sent or '-'}")
        findings[catalogue] = tally
        report[catalogue] = (keys, duplicates)

    print("\n=== summary ===")
    for catalogue, tally in findings.items():
        keys, duplicates = report[catalogue]
        uuids = sum(1 for k in keys if UUID.match(k))
        print(f"  {catalogue}:")
        for label, count in tally.most_common():
            print(f"    {count:>2} / {args.runs}  {label}")
        print(f"    keys sent: {len(keys)}, of which UUID-shaped: {uuids}")
        print(f"    runs that left more than one work order on 4471: {duplicates} of {args.runs}")

    generated = findings.get("generated")
    if generated is None:
        return 0
    reached = sum(count for label, count in generated.items()
                  if label.startswith("create_work_order("))
    wrong = sum(count for label, count in generated.items()
                if label.startswith("create_work_order(") and "(meter_check)" not in label)
    print()
    if wrong:
        print(f"  Bonus: {wrong} of {args.runs} generated runs filled type with something other")
        print("  than meter_check. Show it in the room if it happens; the handout does not rely on it.")
    if reached == args.runs:
        print(f"  Every generated run reached create_work_order, which is the log line the handout")
        print("  reads. c-02's worked tier step one holds on this model.")
        return 0
    print(f"  Only {reached} of {args.runs} generated runs reached create_work_order. The handout's")
    print("  step one says the log line will name that tool with decision allow; on this model it")
    print("  may not, so run the step yourself before the room does, and say what you saw.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
