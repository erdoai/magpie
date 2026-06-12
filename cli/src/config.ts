/**
 * CLI config: ~/.config/magpie/config.json
 *
 * Precedence for each value: env var > config file > default.
 *  - API URL: MAGPIE_API_URL > config.apiUrl > https://magpie.erdo.ai
 *  - Token:   MAGPIE_TOKEN  > config.token
 *  - workspace/project: per-command flags > config (set via `magpie link`)
 */

import { mkdirSync, readFileSync, writeFileSync, existsSync, unlinkSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

export interface MagpieConfig {
  apiUrl?: string;
  token?: string;
  workspace?: string;
  project?: string;
}

const CONFIG_DIR = join(homedir(), '.config', 'magpie');
const CONFIG_PATH = join(CONFIG_DIR, 'config.json');

export const DEFAULT_API_URL = 'https://magpie.erdo.ai';

export function loadConfig(): MagpieConfig {
  if (!existsSync(CONFIG_PATH)) return {};
  try {
    return JSON.parse(readFileSync(CONFIG_PATH, 'utf-8'));
  } catch {
    return {};
  }
}

export function saveConfig(config: MagpieConfig): void {
  mkdirSync(CONFIG_DIR, { recursive: true });
  writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + '\n', { mode: 0o600 });
}

export function clearToken(): void {
  const config = loadConfig();
  delete config.token;
  if (Object.keys(config).length === 0 && existsSync(CONFIG_PATH)) {
    unlinkSync(CONFIG_PATH);
  } else {
    saveConfig(config);
  }
}

export function resolveApiUrl(): string {
  return process.env.MAGPIE_API_URL || loadConfig().apiUrl || DEFAULT_API_URL;
}

export function resolveToken(): string | undefined {
  return process.env.MAGPIE_TOKEN || loadConfig().token;
}
