/** ACE Bridge configuration for TypeScript adapters. */

export interface ACEConfig {
  /** Path to ACE runtime root directory */
  aceRoot: string;
  /** Path to Python executable for bridge */
  python: string;
  /** Path to ace_host_adapter.py */
  adapterScript: string;
  /** Path to ace_capsule.py */
  capsuleScript: string;
  /** LLM endpoint URL */
  llmEndpoint: string;
  /** LLM model name */
  model: string;
  /** API key for LLM */
  apiKey: string;
  /** Lab directory for proofs/reports */
  labDir: string;
  /** Default request timeout (ms) */
  requestTimeout: number;
  /** CLI timeout (ms) */
  cliTimeout: number;
}

function getEnv(key: string, defaultValue: string): string {
  return process.env[key] ?? defaultValue;
}

function getEnvInt(key: string, defaultValue: number): number {
  const val = process.env[key];
  return val ? parseInt(val, 10) : defaultValue;
}

/** Load configuration from environment variables with sensible defaults. */
export function loadConfig(): ACEConfig {
  return {
    aceRoot: getEnv("ACE_BRIDGE_ROOT", "C:\\tmp\\ace_core"),
    python: getEnv("ACE_BRIDGE_PYTHON", "C:\\tmp\\ace-host-adapter-lab\\.venv\\Scripts\\python.exe"),
    adapterScript: getEnv("ACE_ADAPTER_SCRIPT", "C:\\tmp\\ace-host-adapter-lab\\ace_host_adapter.py"),
    capsuleScript: getEnv("ACE_CAPSULE_SCRIPT", "C:\\tmp\\ace-host-adapter-lab\\ace_capsule.py"),
    llmEndpoint: getEnv("ACE_LLM_ENDPOINT", "http://127.0.0.1:3000/v1/chat/completions"),
    model: getEnv("ACE_LLM_MODEL", "nemotron-3.5-lightning-free"),
    apiKey: getEnv("ACE_LLM_API_KEY", "sk-local"),
    labDir: getEnv("ACE_LAB_DIR", "C:\\tmp\\ace-host-adapter-lab"),
    requestTimeout: getEnvInt("ACE_REQUEST_TIMEOUT", 15000),
    cliTimeout: getEnvInt("ACE_CLI_TIMEOUT", 60000),
  };
}

/** Global config instance (singleton) */
let _config: ACEConfig | null = null;

export function getConfig(): ACEConfig {
  if (!_config) {
    _config = loadConfig();
  }
  return _config;
}

export function setConfig(config: Partial<ACEConfig>): void {
  _config = { ...getConfig(), ...config };
}