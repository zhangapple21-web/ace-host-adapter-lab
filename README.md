# ACE Host Adapter Lab

Status: experimental, read-only, not admitted to ACE production.

## Ownership

- ACE source of truth: `C:\tmp\ace_core` (AceDaemon and TaskPool).
- PI experiment checkout: `C:\tmp\PI-Desktop-ace-lab` (unchanged).
- This adapter is host-neutral: Trae, Codex, PI, or another client may implement
  the same JSON-lines transport. No host has governance authority by registration.
- No ACE imports, daemon startup, model calls, task claims, or production writes.

## Contract

Input and output are one JSON object per line over stdin/stdout.

```json
{"protocol":"ace.host_adapter.v0","request_id":"r1","host_id":"pi","action":"capabilities"}
```

Supported reads: `capabilities`, `status`, `tasks` (`limit`, default 20, max 100).
`request_task`, `approve`, `execute`, and `cancel` are recognized but always
REFUSED. Unknown actions and incompatible protocol versions are refused.

`host_id` and `request_id` are correlation labels, NOT authenticated identities
or authorization evidence. The JSON-lines adapter has no network listener. The separate MCP facade uses stdio only.

Status reads the default persisted file at
`06_RUNTIME/ace/data/memory/daemon_state.json`. It never constructs AceDaemon.
Custom configuration paths are not discovered by reading private configuration:
missing default snapshots return unavailable. Snapshot contents do not prove
process liveness (`liveness: UNKNOWN`). Task reads use the eight current TaskPool
status directories and project only scalar ID/status/priority/timestamp fields.
No titles, task bodies, evidence, claim credentials, configuration, or keys are
returned. Projection is data minimization, not governed export approval.
Reads reject resolved paths outside the ACE root and files larger than 1 MiB.
Task listings are bounded previews, not complete or atomic TaskPool inventories.

## Run

```powershell
'{"protocol":"ace.host_adapter.v0","request_id":"r1","host_id":"codex","action":"capabilities"}' | py -3.11 C:\tmp\ace-host-adapter-lab\ace_host_adapter.py C:\tmp\ace_core
```

## Verify

```powershell
Set-Location C:\tmp\ace-host-adapter-lab
py -3.11 -m unittest -v test_adapter
```

Tests use isolated temporary fixtures and never invoke ACE. No dependencies.

## Next Gate

A real host integration must bind authenticated session context and cancellation,
classify exported data, and independently verify ACE's existing execution and
Worker Capsule credentials before enabling any mutation. Reuse
`ops.worker_capsule_cli`/`core.ace_start`; do not create a second TaskPool,
scheduler, governance entry, or memory store. PI plugin permission gateways do
not fully sandbox the plugin Node process or govern every native agent tool.
Keep cooperation-mode and enforced-control claims separate.

## Rollback

Stop the adapter process and remove this lab directory. Neither ACE nor PI
requires it, and no production configuration or plugin installation is changed.

## MCP Delivery

`ace_mcp_server.py` is a host-independent stdio MCP server using the official
Python MCP SDK (1.30.0). It exposes only `ace_capabilities`, `ace_status`, and
`ace_tasks`. No mutation tool is registered. Read-only annotations describe
behavior; they do not authenticate a host or enforce control over its other tools.

The isolated `.venv` is installed locally. Start with:

```powershell
C:\tmp\ace-host-adapter-lab\.venv\Scripts\python.exe -B C:\tmp\ace-host-adapter-lab\ace_mcp_server.py --ace-root C:\tmp\ace_core
```

The process expects MCP messages on stdin, not an interactive terminal.
`mcp-config.json` contains a standard `mcpServers` entry for import into hosts
that accept this JSON format. It uses absolute paths for this machine. Other
hosts can use the same command and arguments in their MCP settings. This file
has not been merged into any global host configuration.

To recreate the environment:

```powershell
py -3.11 -m venv C:\tmp\ace-host-adapter-lab\.venv
C:\tmp\ace-host-adapter-lab\.venv\Scripts\python.exe -m pip install -r C:\tmp\ace-host-adapter-lab\requirements.txt
```

Verify both layers:

```powershell
Set-Location C:\tmp\ace-host-adapter-lab
.\.venv\Scripts\python.exe -B -m unittest -v test_adapter test_mcp
```

Eight tests pass, including an actual subprocess MCP handshake and tool calls
against temporary fixtures, projection checks, invalid-limit rejection,
unknown execution-tool rejection, and byte-for-byte fixture preservation.

PI plugin scaffolding/automatic loading requires an open workspace and was
not available in this session. No PI plugin was installed or packaged. This
MCP service is ready for host registration but is not production-admitted.
