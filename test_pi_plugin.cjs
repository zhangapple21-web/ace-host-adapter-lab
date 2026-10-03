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
  assert.equal(tools.size, 8)
  const capabilities = await tools.get('ace_capabilities').execute({});
  assert.equal(capabilities.status, 'READY');
  assert.equal(capabilities.mutation_policy, 'fail_closed');
  const status = await tools.get('ace_status').execute({});
  assert.equal(status.status, 'OK');
  const tasks = await tools.get('ace_tasks').execute({ limit: 2 });
  assert.equal(tasks.status, 'OK');
  assert(tasks.tasks.length <= 2);
  const refused = await tools.get('ace_capsule').execute({ command: 'execute', pool: 'scratch', scratch_name: 'noop' });
  assert.equal(refused.reason, 'unknown_or_disabled_command');
  await assert.rejects(plugin.invoke('execute', {}), /mutation_disabled/);
  await assert.rejects(plugin.invoke('tasks', { limit: 0 }), /invalid_limit/);
  await assert.rejects(plugin.invoke('tasks', { limit: 1.5 }), /invalid_limit/);
  await assert.rejects(plugin.invoke('status', { command: 'execute' }), /invalid_arguments/);
  await plugin.onUnload();
  assert.equal(tools.size, 0);
  console.log('PASS: 4 tools, real reads, capsule refusal, unload.');
})().catch(error => { console.error(error); process.exitCode = 1; });
