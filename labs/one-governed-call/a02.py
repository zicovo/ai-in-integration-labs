# one-governed-call's worked tier, the four blocks of the handout in one file, unchanged.
# verify.sh checks that this file and the handout still say the same thing.

TOOL = {
    "type": "function",
    "function": {
        "name": "get_meter_readings",
        "description": "Return the meter readings for one Aquaflux connection over a period. "
                       "Use it whenever a question is about consumption or a bill. "
                       "Use the connection id exactly as given in the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The Aquaflux connection id, digits only"},
                "from": {"type": "string", "format": "date"},
                "to": {"type": "string", "format": "date"},
            },
            "required": ["connection_id", "from", "to"],
            "additionalProperties": False,
        },
    },
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "confidence": {"type": "number"},
        "proposed_action": {"type": "string", "enum": ["none", "meter_check", "contact_customer"]},
    },
    "required": ["explanation", "confidence", "proposed_action"],
    "additionalProperties": False,
}

import json, os, requests

GATEWAY = "https://models.aquaflux.internal:4000/v1/chat/completions"
HEADERS = {"Authorization": f"Bearer {os.environ['LAB_GATEWAY_KEY']}"}
INSTRUCTIONS = ("You explain water consumption to Aquaflux service desk staff. "
                "Use the tool for readings. Never guess a value.")
QUESTION = ("why is the bill for connection 4471 so high between 2026-01-01 and 2026-06-30, "
            "and can we check the meter?")

def call(model, messages, tools=None, schema=None):
    body = {"model": model, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": True}}
    return requests.post(GATEWAY, headers=HEADERS, json=body, timeout=300).json()["choices"][0]["message"]

def run(model):
    messages = [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": QUESTION}]
    first = call(model, messages, tools=[TOOL])
    tool_call = first["tool_calls"][0]
    args = json.loads(tool_call["function"]["arguments"])
    readings = requests.get("https://mdm.aquaflux.internal/readings", params=args, timeout=10).json()
    messages += [first, {"role": "tool", "tool_call_id": tool_call["id"], "content": json.dumps(readings)}]
    final = call(model, messages, schema=ANSWER_SCHEMA)
    return {"tool_call": args, "answer": json.loads(final["content"]), "readings": readings}

def checks(result, question_connection="4471"):
    out = {}
    out["schema_valid"] = set(result["answer"]) == {"explanation", "confidence", "proposed_action"}
    out["tool_names_requested_connection"] = result["tool_call"]["connection_id"] == question_connection
    out["action_in_allowed_list"] = result["answer"]["proposed_action"] in ("none", "meter_check", "contact_customer")
    out["readings_were_used"] = len(result["readings"]) > 0 and "March" in result["answer"]["explanation"]
    return out

for model in ("aquaflux-default", "aquaflux-alt"):
    for i in range(3):
        r = run(model)
        print(model, i, checks(r), r["tool_call"])
