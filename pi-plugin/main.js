'use strict';
const { execFile } = require('node:child_process');
const { randomUUID } = require('node:crypto');

function getEnv(key, defaultValue) {
  return process.env[key] ?? defaultValue;
}

const python = getEnv('ACE_BRIDGE_PYTHON', 'C:\\tmp\\ace-host-adapter-lab\\.venv\\Scripts\\python.exe');
const adapter = getEnv('ACE_ADAPTER_SCRIPT', 'C:\\tmp\\ace-host-adapter-lab\\ace_host_adapter.py');
const capsule = getEnv('ACE_CAPSULE_SCRIPT', 'C:\\tmp\\ace-host-adapter-lab\\ace_capsule.py');
const aceRoot = getEnv('ACE_BRIDGE_ROOT', 'C:\\tmp\\ace_core');
// Single source of truth for the tool contract, shared with the Python MCP
// server and pi-plugin/manifest.json. Editing the list here is not supported:
// change tool-surface.json and re-run the tests, which assert all three agree.
const surface = require('../tool-surface.json');
const LIMITS = surface.limits;

// One knob for both hosts: ACE_BRIDGE_CLI_TIMEOUT is what bridge_config.py reads,
// so prefer it and keep ACE_CLI_TIMEOUT working as a legacy fallback.
const requestTimeout = parseInt(getEnv('ACE_REQUEST_TIMEOUT', String(surface.timeouts_ms.request_default)), 10);
const cliTimeout = parseInt(getEnv('ACE_BRIDGE_CLI_TIMEOUT', getEnv('ACE_CLI_TIMEOUT', String(surface.timeouts_ms.cli_default))), 10);

const readTools = surface.read_tools;
const capsuleSchema = surface.capsule_tool.schema;

function runJson(script, args, request, timeout) {
  return new Promise((resolve, reject) => {
    const child = execFile(python, ['-B', script, ...args], { timeout, maxBuffer: 1024 * 1024, windowsHide: true, encoding: 'utf8' }, (error, stdout, stderr) => {
      if (error) {
        const msg = stderr ? String(stderr).slice(0, 500) : 'ace_bridge_process_failed';
        return reject(new Error(msg));
      }
      try { resolve(JSON.parse(String(stdout).trim())); }
      catch { reject(new Error('ace_bridge_response_invalid')); }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify(request) + '\n');
  });
}

function invoke(action, args = {}) {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return Promise.reject(new Error('invalid_arguments'));
  if (action === 'capsule') {
    if (!args.command || typeof args.command !== 'string') {
      return Promise.reject(new Error('capsule_command_required'));
    }
    return runJson(capsule, [], args, cliTimeout);
  }
  const item = readTools.find(tool => tool.action === action);
  if (!item) return Promise.reject(new Error('mutation_disabled'));
  const allowed = action === 'tasks' ? ['limit'] : action === 'query' ? ['query', 'query_type', 'limit'] : [];
  if (Object.keys(args).some(key => !allowed.includes(key))) return Promise.reject(new Error('invalid_arguments'));
  const limit = args.limit === undefined ? LIMITS.default_limit : args.limit;
  if ((action === 'tasks' || action === 'query') && (!Number.isInteger(limit) || limit < LIMITS.task_limit_min || limit > LIMITS.task_limit_max)) return Promise.reject(new Error('invalid_limit'));
  if (action === 'query' && (typeof args.query !== 'string' || args.query.length > LIMITS.query_max_len)) return Promise.reject(new Error('invalid_query'));
  const requestId = randomUUID();
  const requestArgs = action === 'tasks' ? { limit } : action === 'query' ? { query: args.query, query_type: args.query_type || 'auto', limit } : {};
  return runJson(adapter, [aceRoot], { protocol: 'ace.host_adapter.v0', request_id: requestId, host_id: 'pi', action, ...requestArgs }, requestTimeout)
    .then(response => {
      if (response.protocol !== 'ace.host_adapter.v0' || response.request_id !== requestId) throw new Error('ace_bridge_response_invalid');
      return response;
    });
}

async function onLoad() {
  for (const item of readTools) {
    await pi.agent.registerTool({ name: item.name, description: item.description, schema: item.schema, risk: 'low', execute: args => invoke(item.action, args) });
  }
  await pi.agent.registerTool({
    name: 'ace_capsule',
    description: 'Run one existing ACE worker-capsule command. ACE validates credentials and pool face.',
    schema: capsuleSchema,
    risk: 'low',
    execute: args => invoke('capsule', args)
  });
}

async function onUnload() {
  for (const name of [...readTools.map(item => item.name), 'ace_capsule']) await pi.agent.unregisterTool(name);
}

module.exports = { onLoad, onUnload, invoke };