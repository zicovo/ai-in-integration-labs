# Lab: one governed call, tested twice

Lab `one-governed-call`. About 30 minutes in this session.

The lab comes in three versions, called tiers. The **worked tier** gives you all the code and you run
and change it. The **completion tier** leaves two parts for you to write. The **open tier** gives you
only the goal. Today, start in the completion tier; the worked tier is your safety net. The
acceptance check at the end is the same for all three.

## What you can do afterwards

You can make a model call through the model gateway with a structured output schema and one tool
definition, and you can write a check that fails on a schema-valid but wrong tool call.

The skill that matters is drawing a line. On one side is what the model suggests. On the other is
what your code checks before anything is executed. The products used below are just this year's
way of doing it.

## Setup

Everything is installed and connected for you. You do not install anything during the lab. If the
smoke test below fails, ask the instructor.

> **Product facts** in this section were last checked in September 2026. Products change; the
> principle does not.

The model gateway in the stack is the LiteLLM proxy. It is an open-source gateway that speaks the
OpenAI API, forwards requests to many model providers, hands out keys, and enforces budgets, rate
limits and logging. It listens on `https://models.aquaflux.internal:4000`.

Your lab key is in the variable `LAB_GATEWAY_KEY`. It has a budget and every call with it is
logged. Your code never holds a provider key. The model key your instructor gave you sits in
`labs/stack/.env`, where only the gateway reads it.

Behind the gateway, the model is hosted by default. When the stack has no key for a hosted model,
it uses a small open-weight model that runs on your own laptop in Ollama instead. You never need to
know which. The gateway shows either one under the same name, `aquaflux-default`.

A second name, `aquaflux-alt`, points at the same model with extra instructions added by the lab.
That is configuration two, and it is set up to go wrong in a particular way. The smoke test checks
that the model can call tools and return strict JSON.

The lab also has a stand-in for Aquaflux's meter data system. Its readings API is at
`https://mdm.aquaflux.internal/readings` and holds data for about fifty connections. Two of them
matter today: 4471, the customer Nadia is helping, and 4417, somebody else. In this lab your own
script calls the readings API. (In the lab `expose-one-operation`, in this repository, that call
moves behind the tool gateway.)

Run the smoke test first:

```sh
labs/stack/smoke.sh one-governed-call
```

It starts what this lab needs and checks everything this handout relies on.

**You should see** a list of green `ok` lines ending in "Smoke test passed for one-governed-call".
If a line says `FAIL`, stop and ask the instructor.

If you want to see the two services by hand:

```sh
curl -s https://models.aquaflux.internal:4000/v1/models \
  -H "Authorization: Bearer $LAB_GATEWAY_KEY" | jq -c '[.data[].id]'
curl -sG https://mdm.aquaflux.internal/readings -d connection_id=4471 \
  -d from=2026-01-01 -d to=2026-06-30 | jq -c '[.[] | {period, volume_m3}]'
```

**You should see** three model names, `aquaflux-default`, `aquaflux-alt` and `aquaflux-embed` (the
third is for the retrieval labs). Then six months of readings for connection 4471, where the volume
roughly doubles from March.

## The task

Build the reading assistant's step two as one governed call, and then prove something about it.

You will write, or run, a script that does five things.

1. It sends Nadia's question to `aquaflux-default` through the gateway, together with the
   instructions, one tool definition (`get_meter_readings`) and a schema for the answer.
2. It runs the tool call the model suggests.
3. It sends the result back to the model.
4. It reads the final answer, which comes back as JSON.
5. It runs a set of checks on the answer.

Then you run the same script against `aquaflux-alt` and compare.

You are done when all of this is true, whichever tier you pick:

- Both sets of runs appear in the gateway log, with the model name and the token counts.
- The checks pass on the runs from `aquaflux-default`.
- The checks fail on the run from `aquaflux-alt` whose tool call names connection 4417.
- You can say in one sentence which check caught it and why the schema check did not.

## Worked tier

All the code is given. Read it, run it, then change one thing and see what happens. The four
blocks below are, unchanged, in [`a02.py`](a02.py) in this folder.

### Step 1: read the tool definition

This tells the model that a tool exists and how to call it. Look at the description. It is
written for the model, not for a developer. It says what the tool is for and when to use it. The
schema below it lists the arguments and forbids any extra ones.

```python
TOOL = {
    "type": "function",
    "function": {
        "name": "get_meter_readings",
        "description": (
            "Return the meter readings for one Aquaflux connection "
            "over a period. Use it whenever a question is about "
            "consumption or a bill. "
            "Use the connection id exactly as given in the question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {
                    "type": "string",
                    "description": "The Aquaflux connection id, digits only",
                },
                "from": {"type": "string", "format": "date"},
                "to": {"type": "string", "format": "date"},
            },
            "required": ["connection_id", "from", "to"],
            "additionalProperties": False,
        },
    },
}
```

### Step 2: read the answer schema

This is the shape the model's final answer must have: three fields. The last one,
`proposed_action`, may only take one of three values. That list keeps the model's suggestion to
things your code knows how to handle. It is a hint, not a security control.

```python
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "confidence": {"type": "number"},
        "proposed_action": {
            "type": "string",
            "enum": ["none", "meter_check", "contact_customer"],
        },
    },
    "required": ["explanation", "confidence", "proposed_action"],
    "additionalProperties": False,
}
```

### Step 3: read the loop

This is the code around the model, the harness. It calls the model once, runs the tool the model
asked for, and calls the model a second time with the readings.

```python
import json, os, requests

GATEWAY = "https://models.aquaflux.internal:4000/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {os.environ['LAB_GATEWAY_KEY']}"}
INSTRUCTIONS = ("You explain water consumption to Aquaflux service desk "
                "staff. Use the tool for readings. Never guess a value.")
QUESTION = ("why is the bill for connection 4471 so high between "
            "2026-01-01 and 2026-06-30, and can we check the meter?")

def call(model, messages, tools=None, schema=None):
    body = {"model": model, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
    if schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema,
                            "strict": True},
        }
    reply = requests.post(GATEWAY, headers=HEADERS, json=body, timeout=300)
    return reply.json()["choices"][0]["message"]

def run(model):
    messages = [{"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": QUESTION}]
    first = call(model, messages, tools=[TOOL])
    tool_call = first["tool_calls"][0]
    args = json.loads(tool_call["function"]["arguments"])
    readings = requests.get("https://mdm.aquaflux.internal/readings",
                            params=args, timeout=10).json()
    messages += [first, {"role": "tool", "tool_call_id": tool_call["id"],
                         "content": json.dumps(readings)}]
    final = call(model, messages, schema=ANSWER_SCHEMA)
    return {"tool_call": args, "answer": json.loads(final["content"]),
            "readings": readings}
```

### Step 4: read the checks, then run everything

The first three checks are deterministic: a rule decides pass or fail. The fourth is a simple
stand-in for a judged check, which you do not need today.

```python
def checks(result, question_connection="4471"):
    out = {}
    out["schema_valid"] = set(result["answer"]) == {
        "explanation", "confidence", "proposed_action"}
    out["tool_names_requested_connection"] = (
        result["tool_call"]["connection_id"] == question_connection)
    out["action_in_allowed_list"] = result["answer"]["proposed_action"] in (
        "none", "meter_check", "contact_customer")
    out["readings_were_used"] = (
        len(result["readings"]) > 0
        and "March" in result["answer"]["explanation"])
    return out

for model in ("aquaflux-default", "aquaflux-alt"):
    for i in range(3):
        r = run(model)
        print(model, i, checks(r), r["tool_call"])
```

Run it from this folder with `python3 a02.py`. It runs each model three times, so six runs in all.
With the hosted model that takes about a minute. On the local model, allow up to a minute per run.
The second call of each run, the one that explains the readings, is the slow one. Do not start the
run loop in the last five minutes of the lab.

**You should see** six lines. The three `aquaflux-default` lines show `True` for every check and a
tool call for connection `4471`. The three `aquaflux-alt` lines show a tool call for `4417` and
`'tool_names_requested_connection': False`, while `schema_valid` is still `True`.

**If you see something else:** an error about `tool_calls` means the model answered in plain text
instead of calling the tool. Run the script again, and if it keeps happening, ask the instructor.

### Step 5: read the gateway log

Every call went through the gateway, so the gateway knows about all of them. This command shows
the most recent twelve. Each run made two calls, one to choose the tool and one to explain the
readings. The log also holds every earlier call made with your key, so the command sorts by time
first.

```sh
curl -s https://models.aquaflux.internal:4000/spend/logs \
  -H "Authorization: Bearer $LAB_GATEWAY_KEY" \
  | jq -r 'sort_by(.startTime) | .[-12:][]
      | [.startTime[11:19], .model_group, .model,
         .prompt_tokens, .completion_tokens] | @tsv'
```

**You should see** twelve lines, six for `aquaflux-default` and six for `aquaflux-alt`. Each has
five columns: the time, the name your script asked for (`model_group`), the model that actually
answered (`model`), and the two token counts. You never chose that model, and your script never
named it.

**If you see something else:** fewer than twelve lines means the gateway has not written its last
calls down yet; it does so every second. Run the command again.

### Step 6: change one thing

Open the file and delete the line that says "Use the connection id exactly as given in the
question" from the tool description. In the last loop, change `("aquaflux-default", "aquaflux-alt")`
to `("aquaflux-alt",)` so only configuration two runs. Run it again and count how often 4417
appears in the three lines.

The description is a prompt, and you have just measured what that sentence was worth. Keep the
number for the debrief.

## Completion tier

The call, the tool definition and the loop are the same as in the worked tier. Two parts are yours
to write. There is no separate starter file: copy `a02.py` to `my_a02.py`, cut `ANSWER_SCHEMA` back
to only `explanation`, cut `checks` back to only `schema_valid`, and then rebuild them without
looking at the worked tier.

1. **The answer schema.** Add `confidence` as a number and `proposed_action` as a list of exactly
   three allowed values that you choose. Forbid extra fields.
2. **The `checks` function.** Add a check that compares the connection id in the tool call with
   the one in the question. Then add one more deterministic check of your own. A good one checks
   that the period the model asked for includes the month the bill is about.

Run both configurations three times each and collect what the acceptance check asks for.

**Stretch:** add a fifth check that the period asked for includes March, run your checks against
`aquaflux-alt`, and explain the difference.

## Open tier

You get the goal, the two model names, the readings API and the acceptance check. You design the
rest: the instructions, the tool definition, the answer schema, the loop and the checks.

Three rules:

- The model is never given the address of the readings API. Your code calls it.
- The list of allowed actions includes one that means "do nothing".
- At least three of your checks are deterministic.

Run each configuration five times. Report the pass rate of each check for each configuration in a
small table. Then write two sentences. Which check would a judged evaluation add that yours cannot?
And why would you still run yours first?

## The deliberate failure

Configuration two is set up so that at least one run asks `get_meter_readings` for connection 4417
instead of 4471. The arguments are a well-formed string and two valid dates, so the schema accepts
them.

If your checks stop at the schema, the run looks green. The customer at 4471 is then told about
somebody else's water use, with a confidence number the model made up.

There are two ways to notice. Your content check fails, or you read the tool call in the output
and see the swapped digits.

The fix is the content check, a single comparison. A second change makes the mistake less likely
in the first place. Give the model the connection id as a separate field in the request, instead
of as part of a sentence it has to copy. Make both changes. Then say which one is a control and
which one is only a convenience.

## Acceptance check

- [ ] Both configurations appear in the gateway log, with model name and token counts.
- [ ] Your checks pass on every run from `aquaflux-default`.
- [ ] Your checks fail on the run from `aquaflux-alt` that names 4417, and the check that fails is
      the one comparing the tool call with the question.
- [ ] You can say in one sentence why the schema check let the wrong call through.
- [ ] You saved the output of your runs, because running again will not give the same output.

## Take it back

Think of an agent or a script that calls a model, at a client, in your internship or in a project
of your own. Where is its output checked: on shape, on meaning, or not at all? Write down the first
five inputs of the eval set it should have had.
