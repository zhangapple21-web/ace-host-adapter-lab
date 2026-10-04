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

## Known Defect (upstream, ACE core)

`ace_capsule` is wired and its read/claim paths are verified, but `render` and
therefore `submit` fail. The failure is in ACE core, not in this adapter.

`core/worker_capsule.py:732` calls `validate_execution_discipline(task)`, which
reaches `core/execution_discipline.py:549`:

```python
"last_event": envelope.get("last_event"),
```

`envelope` is a dataclass instance in this function — every sibling access uses
attribute form (`envelope.complexity`, `envelope.protocol`,
`envelope.start_protocol`, `envelope.pipeline`, `envelope.events`,
`envelope.status`, `envelope.stop`). `last_event` is a declared field at
`core/execution_discipline.py:68`. The `.get(...)` call therefore raises
`AttributeError: 'ExecutionDiscipline' object has no attribute 'get'`, ACE's
CLI exits non-zero with no stdout, and this adapter correctly reports
`ACE_CLI_OUTPUT_INVALID` with `stdout_lines: 0`.

Reproduced by `test_capsule.test_scratch_round_trip_and_refusals`, which is
currently RED (`AssertionError: 'REFUSED' != 'CAPSULE_READY'`). `list-pending`,
`show`, and `start` pass. The one-line candidate fix is
`getattr(envelope, "last_event", None)` at line 549, but it lives in ACE core
and is not owned by this lab, so it is left unfixed and reported rather than
patched here.

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
Python MCP SDK (1.30.0). It registers ten tools: `ace_capabilities`,
`ace_status`, `ace_tasks`, `ace_learning`, `ace_archaeology`, `ace_governance`,
`ace_query`, `ace_health`, `ace_metrics`, and `ace_capsule`.

The first nine carry `readOnlyHint=True`. `ace_capsule` deliberately does not:
it invokes ACE's existing `ops.worker_capsule_cli` and can transition a real task
state. It exposes no shell, accepts no arbitrary pool path, defaults to
`pool=production`, and routes every mutation through ACE's own claim, fencing
token, and pool-face validation. A `REFUSED` result is final for that call.
Read-only annotations describe behavior; they do not authenticate a host or
enforce control over its other tools.

The isolated `.venv` is installed locally. Start with:

```powershell
C:\tmp\ace-host-adapter-lab\.venv\Scripts\python.exe -B C:\tmp\ace-host-adapter-lab\ace_mcp_server.py --ace-root C:\tmp\ace_core
```

The process expects MCP messages on stdin, not an interactive terminal.
`mcp-config.json` contains a standard `mcpServers` entry for import into hosts
that accept this JSON format. It uses absolute paths for this machine. Other
hosts can use the same command and arguments in their MCP settings.

As of 2026-10-04 this server is registered in the OpenCode global configuration
at `~/.config/opencode/opencode.json` under `mcp.servers.ace-readonly`, so all
ten tools are reachable from any OpenCode project. The `opencode mcp add` CLI
was not on PATH on this machine, so the entry was written by hand; it was the
only file created and no pre-existing global settings were overwritten.

To recreate the environment:

```powershell
py -3.11 -m venv C:\tmp\ace-host-adapter-lab\.venv
C:\tmp\ace-host-adapter-lab\.venv\Scripts\python.exe -m pip install -r C:\tmp\ace-host-adapter-lab\requirements.txt
```

Verify both layers:

```powershell
Set-Location C:\tmp\ace-host-adapter-lab
.\.venv\Scripts\python.exe -B -m unittest -v test_adapter test_mcp test_capsule
```

Eight adapter/MCP tests pass, including an actual subprocess MCP handshake and
tool calls against temporary fixtures, projection checks, invalid-limit
rejection, unknown execution-tool rejection, and byte-for-byte fixture
preservation. The ninth, `test_capsule`, is RED for the upstream reason recorded
above; see Known Defect.

PI plugin scaffolding/automatic loading requires an open workspace and was
not available in this session. No PI plugin was installed or packaged by this
work. The MCP service is registered in OpenCode and is still not
production-admitted.
