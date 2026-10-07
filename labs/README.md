# The lab stack, for participants

Everything a handout names is on this page: the addresses, the people, and the scripts. Run every
command in the dev container's terminal.

## Addresses

Every service answers on its own `aquaflux.internal` name over https, in the dev container's
terminal and in the lab browser (`aqx ui`, then <http://localhost:3000>). They do not resolve in
the browser on your own machine, on purpose: one network, one set of names.

| Service | Address | What it is |
| --- | --- | --- |
| Start page | `https://aquaflux.internal` | Links to everything below |
| Work order management | `https://wom.aquaflux.internal` | A read-only page of every work order; the API is at `/v4`, described at `/docs` |
| Customer information system | `https://cis.aquaflux.internal` | The open dunning cases and their notes; API described at `/docs` |
| Meter data management | `https://mdm.aquaflux.internal` | Monthly consumption per connection; API described at `/docs` |
| Identity provider | `https://idp.aquaflux.internal` | Keycloak, realm `aquaflux` |
| Model gateway | `https://models.aquaflux.internal:4000` | LiteLLM. Serves `aquaflux-default` and `aquaflux-alt` |
| Tool gateway | `https://tools.aquaflux.internal:4444` | The door in front of every tool. `/tools` the catalogue, `/logs` the decision log, `/policy` the active policy |
| Policy engine | `https://policy.aquaflux.internal:8181` | Open Policy Agent. `/v1/policies` shows what is loaded |
| Approval service | `https://approvals.aquaflux.internal/approvals` | The approvals currently active |
| Trace viewer | `https://traces.aquaflux.internal:16686` | Jaeger |
| Workflow engine | `https://workflow.aquaflux.internal:8233` | Temporal, development mode |
| Vector engine | `https://vectors.aquaflux.internal:6333/dashboard` | Qdrant, empty until you fill it |
| Database | `db.aquaflux.internal:5432` | PostgreSQL with pgvector. `psql "$AQUAFLUX_DB"` connects |

## The people

The scenario is Aquaflux, a water utility. Its people are users in the `aquaflux` realm, and each
one's password is their user name. They sign in from the terminal, in the steps that need them.

| User | Role |
| --- | --- |
| `nadia` | service desk |
| `tom` | field technician |
| `els` | collections officer |
| `sam` | collections team lead |
| `priya` | integration engineer |

The identity provider's administration console signs in as `admin` / `admin`, which lives in
Keycloak's own `master` realm; it opens on the `aquaflux` realm's people and clients.

The model gateway's key is in `$LAB_GATEWAY_KEY`.

## Scripts

| Command | Does |
| --- | --- |
| `labs/stack/smoke.sh <module>` | Starts what one lab needs, resets its data, and checks the handout's preconditions. Run it first, every lab |
| `aqx help` | The helper commands the handouts use: the decision log, fixtures, policies, traces, the lab browser |
| `aqx ui` | Starts the lab browser at <http://localhost:3000> |
| `aqx reset` | Puts the seeded work orders, dunning cases and approvals back |
| `aqx down` | Stops the stack |
| `labs/stack/ask.sh` | Runs the reading assistant, the agent expose-one-operation, carry-the-authority and reconstruct-one-transaction use |
| `labs/stack/register-tool-server.sh <dir> <port>` | Starts an MCP server from a directory and registers it at the tool gateway |
| `labs/stack/approve.sh` | Records an approval, signing the approver in at that moment |
| `labs/stack/start-worker.sh <dir>`, `labs/stack/kill-worker.sh` | survive-the-crash: start the workflow worker on a directory, and kill it without warning |
| `labs/stack/run-workflow.sh` | survive-the-crash: start a run and follow it |

## When something is wrong

- A smoke test line that says `FAIL` is the stack's problem, not yours. Send the output to your
  instructor.
- `command not found` for `jq`, `psql` or `opa` means the command ran on your own machine. Use the
  dev container's terminal.
- A page that says the address cannot be found is in the browser on your own machine. Use the lab
  browser, `aqx ui`.
