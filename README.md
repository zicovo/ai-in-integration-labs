# AI in Integration: the labs

Hands-on labs for **AI in Integration**, the i8c academy programme by steerio. Every agent action
is an integration. Identity, policy and audit belong there, not in a prompt.

This repository is everything you need to run the labs on your own laptop: a dev container and a
local stack of open source services (an identity provider, a model gateway, a tool gateway, a
policy engine, a trace store, a workflow engine and three small Aquaflux systems of record).
The lab handouts are separate PDFs; your instructor tells you where to find them.

Nothing here is installed on your machine by hand. Everything runs in Docker.

## What you need

- **Docker**: Docker Desktop on macOS or Windows (with WSL 2), or Docker Engine on Linux.
  Give Docker **at least 8 GB of memory** and keep **about 20 GB of disk** free.
- **VS Code** with the **Dev Containers** extension, or the dev container command line
  (`npx @devcontainers/cli`, which needs Node.js 22 or newer).
- **Git**, and access to this repository.
- **Internet access** for the first start: roughly 2 to 3 GB of images and models are downloaded
  once. Do this before the session, not on shared wifi.
- Optional: **a model key** from your instructor, which goes in `labs/stack/.env` (below). Without
  one the labs run on a small local model, which is slower and works for every lab.

Apple Silicon Macs are supported: every image publishes an arm64 build.

## Set up, once, before the session

```sh
git clone <this repository>
cd <the folder it made>
```

If your instructor gave you a model key, copy the example and fill it in:

```sh
cp labs/stack/.env.example labs/stack/.env
# then edit labs/stack/.env
```

Open the folder in the dev container:

- **VS Code:** open the folder and choose **Reopen in Container** when it offers, or run
  *Dev Containers: Reopen in Container* from the command palette.
- **Command line:** `npx @devcontainers/cli up --workspace-folder .`, then
  `docker exec -it -u vscode -w /workspaces/agentic-integration-academy aquaflux-labs-workspace-1 bash`
  for a terminal inside it.

The first build takes a few minutes. When it is done, the terminal prints a welcome. Then, **in the
dev container's terminal**, run the first smoke test:

```sh
labs/stack/smoke.sh a-02
```

It starts what module a-02 needs, pulls a model if it has to, and checks everything the handout
promises. A list of green `ok` lines ending in "Smoke test passed" means you are ready. If a line
says `FAIL`, that is the stack's problem, not yours: send the output to your instructor.

## During the labs

- **Run every command in the dev container's terminal.** Tools such as `jq`, `psql` and `opa` are
  installed there and not on your machine.
- **Every lab starts with its smoke test:** `labs/stack/smoke.sh <module>`, for example
  `labs/stack/smoke.sh c-02`. It starts only what that lab needs and puts the lab's data back the
  way the handout expects.
- **A browser on the lab network:** `aqx ui`, then open <http://localhost:3000>. Its start page
  lists every service, and the lab's certificate is already trusted there.
- `aqx help` lists the small helper commands the handouts use. `labs/README.md` lists the
  addresses, the people in the scenario and the scripts.

## When you are done

```sh
aqx down
```

stops the stack. Your work stays in the files you edited.
