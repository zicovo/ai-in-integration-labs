# The Aquaflux audit schema

The attribute names the audit store reads. Frameworks emit `gen_ai.*` names that are at
Development status and move between releases; the collector maps whatever arrives into these
names (`collector.yaml`, the `attributes/audit-schema` processor), and the auditor's report, the
retention rule and this lab read these and never the framework's attribute of the month.

One page, on purpose. Read it before you search; you are looking for these keys.

## The join

| Name | Where it is written | What it joins |
| --- | --- | --- |
| trace id | issued by the agent runtime at the start of a run, carried as `traceparent` on every call | everything below to one run. The decision record carries it as `trace_id` |
| `aquaflux.gateway.call_id` | the agent's tool span and the gateway's span and decision record | one tool call to the decision made about it |
| `aquaflux.arguments_sha256` | the agent's tool span and the gateway's decision record | what the agent says it sent to what the gateway decided on. If they differ, read both |
| `aquaflux.idempotency_key` | the agent's tool span, once the adapter writes it | the tool span to the work order record (`idempotency_key` on the work order) |
| `aquaflux.work_order.id` | the agent's tool span, once the adapter writes it; the decision record as `work_order_id` | the run to the record the regulator started from |

## The eight artefacts, as attributes

| # | Artefact | Attribute or record | Written by |
| --- | --- | --- | --- |
| 1 | Trace skeleton | the spans: `invoke_agent <agent>`, `chat <model>`, `execute_tool <tool>`, `tool_gateway <tool>`, the model gateway's own | agent runtime, tool gateway, model gateway |
| 2 | Content | `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`; present only when `aquaflux.content.captured` is true | agent runtime, gated by `AQUAFLUX_CAPTURE_CONTENT` |
| 3 | Model and prompt version | `aquaflux.model.requested`, `aquaflux.model.answered`, `aquaflux.model.deployment_id`, `aquaflux.model.api_base`, `aquaflux.prompt.version` | agent runtime, from the model gateway's answer and headers |
| 4 | Identity chain | `aquaflux.agent`, `aquaflux.person` on the root span; `agent`, `person`, `actor_claim` on the decision record, read from the token the gateway saw | agent runtime claims it; the gateway records what the token said |
| 5 | Policy decision | the decision record: `decision`, `rule`, `policy`, `policy_version`, `reason`, `approvals`, `approval_id` | tool gateway, to its own file; the collector reads the file |
| 6 | Retrieval lineage | `aquaflux.retrieval.documents` | not produced in this lab; b-02's agent would write it |
| 7 | Evaluation and screening verdicts | `aquaflux.evaluation.*` | not produced in this lab |
| 8 | System of record confirmation | `aquaflux.work_order.id` and `aquaflux.idempotency_key` on the tool span; `work_order_id` on the decision record | agent runtime, from what the API returned, if the adapter writes it |

## Where to read

| Store | Address | Holds | Retention |
| --- | --- | --- | --- |
| Trace viewer | `https://traces.aquaflux.internal:16686` and its query API under `/api/v3/` | the spans, for debugging | memory; gone on restart, the seed puts the history back |
| Audit store | `https://collector.aquaflux.internal:13133/audit/audit.jsonl` | spans normalised to this schema, and the decision records once the receiver is wired | a file on a volume you control; append only |
| Gateway decision log | `https://tools.aquaflux.internal:4444/logs` and the file behind it | the decision records, newest last | the last five hundred in memory; the file keeps them all |

`aqx trace`, `aqx audit` and `aqx log` read the three. The regulator's question starts from the
work order, `https://wom.aquaflux.internal/v4/work-orders/<id>`, which returns `idempotency_key`
and `created_at`: the two ways back into the run, one by key and one by guessing at time.
