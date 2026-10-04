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

## Incident: transient dirty-tree state in ACE core (2026-10-04)

`ace_capsule` `render`, and therefore `submit`, failed during wiring. The failure
was NOT in ACE's committed code and is NOT owned by this lab.

Observed failure: `core/worker_capsule.py:732` calls
`validate_execution_discipline(task)`, which reached
`core/execution_discipline.py:549` with `envelope.get("last_event")`.
`envelope` is a dataclass instance in that function — every sibling access uses
attribute form (`envelope.complexity`, `envelope.protocol`,
`envelope.start_protocol`, `envelope.pipeline`, `envelope.events`,
`envelope.status`, `envelope.stop`), and `last_event` is a declared field at
line 68. The `.get(...)` form therefore raised
`AttributeError: 'ExecutionDiscipline' object has no attribute 'get'`, ACE's CLI
exited non-zero with no stdout, and this adapter correctly reported
`ACE_CLI_OUTPUT_INVALID` with `stdout_lines: 0`.

Actual cause: `C:\tmp\ace_core` was a dirty working tree carrying that line as
an uncommitted local modification. `HEAD` has always contained the correct
`envelope.last_event` (`git show HEAD:core/execution_discipline.py`), verified
with `git diff` empty and `git ls-files -v` reporting `H` (no
`assume-unchanged`/`skip-worktree`). Between 14:11 and 14:18 a concurrent
process reverted tracked files to `HEAD`, which removed the bad line.
`test_capsule` went RED -> GREEN as a consequence of that revert, not of any
change made here.

`07_SANDBOX/opencode_tasks/run_canonical_probe.py` monkey-patches this function
with the note "FIXED: use attribute access". That probe is evidence the defect
was previously observed and worked around, and remains in place.

`C:\tmp\ace_core` is under concurrent development by another actor. Observed
being written during this work: `core/coordinate_dynamics.py` (14:28),
`core/counterexample_executor.py` (14:32), `core/lazy_cat_audit.py` (14:37),
`ops/worker_capsule_cli.py` (14:18), plus matching tests. Treat this lab as the
only thing owned here; do not edit `ace_core` from this project.

Separate, still-open ACE core defect, not touched:
`ops/test_execution_discipline.py` has 3 failures
(`test_structured_envelope_preserves_unknowns_and_forbids_unsupported_mechanisms`,
`test_task_pool_persists_protocol_and_lifecycle_events`,
`test_legacy_task_backfill_is_deterministic`) all raising
`TypeError: 'ExecutionDiscipline' object is not subscriptable`.
`ensure_execution_discipline` returns a dataclass while its callers and the
persistence path subscript it as a mapping. Different function, different
defect; the test that exercises both functions
(`test_protocol_audit_and_receipt_are_deterministic_for_prepared_task`) passes.

## Fixed defect: capsule hung from an MCP host (2026-10-04)

`ace_capsule` calls that spawn the CLI ran to the full timeout when invoked
through an MCP host, while the identical command took ~130 ms standalone.
Measured through OpenCode: `list-pending` 65.7 s, `show` 40.7 s, `start` 180 s
(exactly `cli_timeout`), all returning `ACE_CLI_TIMEOUT`. The in-process read
tools were unaffected (`ace_health` 23 ms, `ace_status` 31 ms), which isolated
the fault to the subprocess spawn path.

Rejected hypothesis: inherited stdin. A probe with the parent's stdin as a pipe
versus a console, and inherited versus `stdin=DEVNULL`, was fast in all four
combinations (96-133 ms), so the child reading stdin was not the cause.

Actual cause: on Windows, `subprocess.run` defaults to `close_fds=False` when
redirecting the standard handles. The child therefore inherited this host's
stdio pipe handles, and `communicate()` blocked waiting for the pipe to close
even though the CLI had already finished. Fixed by passing
`stdin=subprocess.DEVNULL` to the `subprocess.run` call in `ace_capsule.py`,
which also forces `close_fds=True`.

Result through MCP after the fix: `list-pending` 183 ms, and a full
`start` (204 ms) -> `render` (155 ms) -> `submit` (170 ms) round trip returning
`SUBMITTED` with `stored_status: review`. Suite remains 9/9.

`cli_timeout` is now tunable via `ACE_BRIDGE_CLI_TIMEOUT` (seconds, positive
integer, default 60) for hosts running this bridge on a loaded machine. The
OpenCode global config sets 180 as margin, since this host has been observed
running a concurrent `python -m pytest ops -q`. With the handle fix in place
that margin is no longer load-bearing and can be lowered. A `REFUSED` carrying
`ACE_CLI_TIMEOUT` is reported as `retryable: true`.

## Fixed defect: the PI plugin never returned a response (2026-10-04)

Every PI-plugin read tool failed with `ace_bridge_process_failed`. The plugin
spawns `ace_host_adapter.py` per call and waits, but the adapter printed its
response and then refused to exit.

Cause: the adapter reads stdin on a daemon thread feeding a queue, and the main
loop only re-checked EOF *after* `stdin_queue.get(timeout=read_timeout)` expired,
with `read_timeout = 300`. Hitting EOF set `eof_event` but nothing woke the
blocked `get()`, so the process lingered up to 300 s after answering. The plugin's
`requestTimeout` is 15 s, so every call timed out and surfaced as a process
failure with empty stderr. Measured directly: response printed, process still
alive after 120 s.

The MCP path was never affected because it calls `handle()` in-process and does
not use this loop. That is why the Python suite passed while the plugin was
completely non-functional.

Fixed in `ace_host_adapter.py` by posting an `_EOF` sentinel onto the queue when
the reader thread finishes, so EOF wakes the blocked `get()` immediately. The
idle timeout is retained for hosts that hold the pipe open.

A rejected hypothesis is worth recording: this was *not* the same Windows handle
inheritance bug fixed above. That one lived in `ace_capsule.py`'s
`subprocess.run`; the PI path already avoided it by calling `child.stdin.end()`
explicitly.

## Fixed defect: `ace_metrics` could only ever be empty (2026-10-04)

`metrics_enabled` defaulted to `False`, so `MetricsCollector.record_*` was a
permanent no-op and the registered `ace_metrics` tool returned empty counters
forever. Now enabled. Keys are `<action>:<status>` and `<action>:<error_code>`,
bounded by the action set and the error-code enum, so growth is bounded.

Verified in a fresh process: five `handle()` calls yield
`{"status:OK": 2, "tasks:OK": 1, "capabilities:READY": 1, "learning:OK": 1}`
plus per-key averages.

Note `get_metrics()` latches `enabled` from the first config it is handed, and
`ace_host_adapter.py:251` serves the `metrics` action *before* the recording call
at line 267, so a `metrics` request never counts itself. Both are harmless, but
a long-lived host must be restarted to pick up config changes; rewriting
`opencode.json` did not reliably restart the MCP process on this machine.

`errors_total` was permanently empty: `record_error_metric` was imported in
`ace_host_adapter.py` but never called, and seven early refusal returns
(protocol mismatch, rate limit, mutation disabled, unknown action, invalid
arguments/limit/query) plus `health` all bypassed the timing block entirely, so
refusals never reached `requests_total` either.

Now instrumented at the single point every refusal already funnels through,
`_refuse_response`. Measured in a fresh process:

```
requests_total: {"status:OK": 1, "tasks:OK": 2, "capabilities:READY": 1,
                 "execute:REFUSED": 1, "approve:REFUSED": 1, "cancel:REFUSED": 1,
                 "request_task:REFUSED": 1, "nope:REFUSED": 1, "status:REFUSED": 1}
errors_total:   {"execute:MUTATION_DISABLED": 1, "approve:MUTATION_DISABLED": 1,
                 "cancel:MUTATION_DISABLED": 1, "request_task:MUTATION_DISABLED": 1,
                 "nope:UNKNOWN_ACTION": 1, "status:INVALID_PROTOCOL": 1}
```

The `except Exception` path both refuses and falls through to the timing block,
so the timing block now skips responses carrying an `error` key. Each refusal is
counted exactly once.

`ace_health` is still not recorded: it is a liveness probe and deliberately
returns before the timing block.

## Test status and known drift

- Python: `test_adapter test_mcp test_capsule` — 9/9 pass.
- Plugin: `node test_pi_plugin.cjs` — passes. It was stale and red before this
  work (`assert.equal(tools.size, 8)` against 10 registered tools, a log line
  claiming "4 tools", and a `refused.reason` assertion against a response shape
  that carries the reason at `error.message`). It now asserts the exact
  ten-name set, covers `ace_learning`/`ace_governance`/`ace_query`/`ace_metrics`,
  and documents why cumulative counters are not assertable through the plugin.

`node` is not on PATH on this machine; it lives at
`C:\Program Files\nodejs\node.exe`. `opencode` is not on PATH either, so
`opencode mcp add` and `opencode service restart` were unavailable.

Environment-variable naming is reconciled: `pi-plugin/main.js` now prefers
`ACE_BRIDGE_CLI_TIMEOUT` (the name `bridge_config.py` reads) and keeps
`ACE_CLI_TIMEOUT` as a legacy fallback, so one setting governs both hosts
without breaking an existing PI configuration.

Fail-closed behaviour is verified rather than assumed. All four mutating
actions refuse with `MUTATION_DISABLED` and unknown actions with
`UNKNOWN_ACTION`, confirmed both through `ace_capabilities` and by direct
`handle()` calls.

## Note: the ace-host-shadow plugin

`.opencode/plugins/ace-host-shadow/` predates the decision to let OpenCode
execute these tools. It reserves the bare names `ace_status`, `ace_tasks`,
`ace_capsule` and friends and replaces their `execute` with a defer stub,
returning `ACE_HOST_DEFERRED`.

It only loads when the workspace is this directory, and it no longer matches the
registered tools: OpenCode names an MCP tool `<server>_<tool>`, so the live
tools are `ace_readonly_ace_status` and so on. The plugin's `hostOwned` set
contains the bare names, so rather than intercepting the real tools it would add
defer placeholders alongside them under the bare names. Expect
`ACE_HOST_DEFERRED` from any bare-named `ace_*` tool opened in this workspace,
and use the `ace-readonly` server instead.

Whether that plugin is still wanted at all is a design decision for the owner:
its premise, that OpenCode must never execute these tools, is now contradicted by
the global registration.

## Tool surface: one source of truth

`tool-surface.json` at the repository root is now the single source of truth for
the tool contract. It previously existed in three drifting copies: the Python
MCP server's decorators, `pi-plugin/manifest.json`, and a hardcoded `readTools`
array in `pi-plugin/main.js`. That duplication had already caused two real
failures: a test asserting eight tools against ten registered, and a JS
assertion reading `refused.reason` for a response that carries the reason at
`error.message`.

- `main.js` loads the surface at runtime and derives its tool list, schemas,
  limits, and default timeouts from it.
- `manifest.json` mirrors the surface and was regenerated from it; version
  bumped to 0.4.0. The `ace_capsule` schema now carries the same `command`,
  `pool`, and `failure_type` enums the runtime already enforced, so the host
  manifest and the bridge agree instead of the manifest being looser.
- `test_tool_surface.py` asserts the MCP server, the manifest, the ACE capsule
  command set, and `BridgeConfig` limits all agree with the surface. It fails
  loudly on drift, which is the point.

Adding or renaming a tool means editing `tool-surface.json` and re-running the
tests; editing `main.js` directly is not supported.

Deliberately *not* decoupled: `main.js` still validates `limit` and query length
before spawning, even though `ace_host_adapter.py` validates again. That is
defense in depth at the host boundary and gives a fast local error instead of a
subprocess round trip, so it is duplication worth keeping.

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
preservation. All nine currently pass, including `test_capsule`, which exercises
a real scratch-pool claim, render, and submit round trip through ACE's own CLI.
See the upstream-defect section for what had to be fixed to get there.

PI plugin scaffolding/automatic loading requires an open workspace and was
not available in this session. No PI plugin was installed or packaged by this
work. The MCP service is registered in OpenCode and is still not
production-admitted.
