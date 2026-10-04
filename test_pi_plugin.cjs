'use strict';
const assert = require('node:assert/strict');
const plugin = require('./pi-plugin/main.js');
const tools = new Map();
global.pi = { agent: {
  registerTool: async tool => { assert(!tools.has(tool.name)); tools.set(tool.name, tool); },
  unregisterTool: async name => { tools.delete(name); }
} };
(async () => {
  await plugin.onLoad();
  assert.deepEqual([...tools.keys()].sort(), [
    'ace_archaeology', 'ace_capabilities', 'ace_capsule', 'ace_governance',
    'ace_health', 'ace_learning', 'ace_metrics', 'ace_query', 'ace_status',
    'ace_tasks',
  ]);
  const capabilities = await tools.get('ace_capabilities').execute({});
  assert.equal(capabilities.status, 'READY');
  assert.equal(capabilities.mutation_policy, 'fail_closed');
  const status = await tools.get('ace_status').execute({});
  assert.equal(status.status, 'OK');
  const tasks = await tools.get('ace_tasks').execute({ limit: 2 });
  assert.equal(tasks.status, 'OK');
  assert(tasks.tasks.length <= 2);
  const learning = await tools.get('ace_learning').execute({});
  assert.equal(learning.status, 'OK');
  const governance = await tools.get('ace_governance').execute({});
  assert.equal(governance.status, 'OK');
  const query = await tools.get('ace_query').execute({ query: 'worker capsule' });
  assert.equal(query.status, 'OK');
  const metrics = await tools.get('ace_metrics').execute({});
  assert.ok(metrics.metrics, 'ace_metrics must report counters, not just a shell');
  // Only the shape is assertable here: each plugin call spawns a fresh adapter
  // process, so its counters are necessarily empty by construction. Cumulative
  // counters are only observable from a long-lived host such as the MCP server.
  for (const key of ['requests_total', 'avg_latency_seconds', 'errors_total']) {
    assert.equal(typeof metrics.metrics[key], 'object', `ace_metrics.${key} must be an object`);
  }
  const refused = await tools.get('ace_capsule').execute({ command: 'execute', pool: 'scratch', scratch_name: 'noop' });
  assert.equal(refused.status, 'REFUSED');
  assert.equal(refused.error.code, 'INVALID_COMMAND');
  assert.equal(refused.error.message, 'unknown_or_disabled_command');
  await assert.rejects(plugin.invoke('execute', {}), /mutation_disabled/);
  await assert.rejects(plugin.invoke('tasks', { limit: 0 }), /invalid_limit/);
  await assert.rejects(plugin.invoke('tasks', { limit: 1.5 }), /invalid_limit/);
  await assert.rejects(plugin.invoke('status', { command: 'execute' }), /invalid_arguments/);
  await plugin.onUnload();
  assert.equal(tools.size, 0);
  console.log('PASS: 10 tools, exact name set, real reads, capsule refusal, unload.');
})().catch(error => { console.error(error); process.exitCode = 1; });
