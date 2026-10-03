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
const requestTimeout = parseInt(getEnv('ACE_REQUEST_TIMEOUT', '15000'), 10);
const cliTimeout = parseInt(getEnv('ACE_CLI_TIMEOUT', '60000'), 10);

const readTools = [
  { name: 'ace_capabilities', action: 'capabilities', description: 'Query ACE bridge capabilities. Read actions do not prove liveness or authorize writes.', schema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'ace_status', action: 'status', description: 'Query ACE persisted status. This does not prove daemon liveness.', schema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'ace_tasks', action: 'tasks', description: 'Query bounded ACE task summaries without task bodies or credentials.', schema: { type: 'object', properties: { limit: { type: 'integer', minimum: 1, maximum: 100 } }, additionalProperties: false } },
  { name: 'ace_learning', action: 'learning', description: 'Read ACE self-evolution snapshot metadata. Read-only; does not prove liveness.', schema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'ace_archaeology', action: 'archaeology', description: 'Read bounded archaeology state and append-only lineage receipts.', schema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'ace_governance', action: 'governance', description: 'Read bounded governance snapshot metadata. No policy mutation.', schema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'ace_query', action: 'query', description: 'Directly query bounded ACE cognition results for map, library, lineage, capability, status, tasks, history, and relations.', schema: { type: 'object', properties: { query: { type: 'string', maxLength: 256 }, query_type: { type: 'string' }, limit: { type: 'integer', minimum: 1, maximum: 100 } }, required: ['query'], additionalProperties: false } },
  { name: 'ace_health', action: 'health', description: 'Health check endpoint for liveness/readiness probes.', schema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'ace_metrics', action: 'metrics', description: 'Return collected metrics (request counts, latency, errors).', schema: { type: 'object', properties: {}, additionalProperties: false } }
];

const capsuleSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['command'],
  properties: {
    command: { type: 'string', enum: ['list-pending', 'show', 'recover', 'reclaim', 'start', 'render', 'renew', 'submit', 'fail'] },
    pool: { type: 'string', enum: ['production', 'scratch'] },
    scratch_name: { type: 'string' },
    task_id: { type: 'string' },
    owner: { type: 'string' },
    actor: { type: 'string' },
    claim: { type: 'string' },
    token: { type: 'integer' },
    reason: { type: 'string' },
    failure_type: { type: 'string', enum: ['retryable', 'permanent', 'manual_gate', 'external_condition'] },
    capsule_hash: { type: 'string' },
    payload: { type: 'object' }
  }
};

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
  const limit = args.limit === undefined ? 20 : args.limit;
  if ((action === 'tasks' || action === 'query') && (!Number.isInteger(limit) || limit < 1 || limit > 100)) return Promise.reject(new Error('invalid_limit'));
  if (action === 'query' && (typeof args.query !== 'string' || args.query.length > 256)) return Promise.reject(new Error('invalid_query'));
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