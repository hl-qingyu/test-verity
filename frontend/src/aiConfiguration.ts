import { apiRequest } from './api/http';

export type CallMode = 'RESPONSES_API' | 'CODEX_EXEC';
export type AISelection = {
  name: string;
  model: string;
  version: number;
  call_mode?: CallMode;
  preference_version?: number;
};
export type Configuration = AISelection & {
  base_url: string;
  reasoning_effort: string;
  has_key: boolean;
};
export type AISettings = {
  personal: Configuration | null;
  cli: Configuration | null;
  call_mode: CallMode;
  preference_version: number;
  cli_runtime: {
    status: 'available' | 'not_installed' | 'unsupported_version' | 'unverified';
    version: string | null;
    available: boolean;
    probe_available?: boolean;
  };
};

export function callModeName(mode?: string) {
  return mode === 'CODEX_EXEC' ? 'Codex CLI' : 'API';
}

export async function readSelectedAI(signal?: AbortSignal) {
  const settings = parseAISettings(await apiRequest<unknown>('/api/ai-service', { signal }));
  const personal = settings.call_mode === 'CODEX_EXEC' ? settings.cli : settings.personal;
  return {
    personal: personal
      ? {
          ...personal,
          call_mode: settings.call_mode,
          preference_version: settings.preference_version,
        }
      : null,
  };
}

export function parseCallMetadata(row: Record<string, unknown>): {
  call_mode: CallMode;
  preference_version?: number;
} {
  const mode = row.call_mode === undefined ? 'RESPONSES_API' : row.call_mode;
  if (mode !== 'RESPONSES_API' && mode !== 'CODEX_EXEC') throw new Error('ai_invalid_response');
  if (
    row.preference_version !== undefined &&
    (!Number.isSafeInteger(row.preference_version) || Number(row.preference_version) < 0)
  )
    throw new Error('ai_invalid_response');
  return { call_mode: mode, preference_version: row.preference_version as number | undefined };
}

export function parseAISettings(value: unknown): AISettings {
  if (!value || typeof value !== 'object') throw new Error('ai_invalid_response');
  const settings = value as Record<string, unknown>;
  for (const key of ['personal', 'cli']) {
    const item = settings[key];
    if (item === null) continue;
    if (!item || typeof item !== 'object') throw new Error('ai_invalid_response');
    const row = item as Record<string, unknown>;
    if (
      !['name', 'base_url', 'model', 'reasoning_effort'].every(
        (field) => typeof row[field] === 'string',
      ) ||
      typeof row.has_key !== 'boolean' ||
      !Number.isSafeInteger(row.version) ||
      Number(row.version) < 1
    )
      throw new Error('ai_invalid_response');
  }
  const runtime = settings.cli_runtime as Record<string, unknown> | null;
  if (
    !['RESPONSES_API', 'CODEX_EXEC'].includes(String(settings.call_mode)) ||
    !Number.isSafeInteger(settings.preference_version) ||
    Number(settings.preference_version) < 0 ||
    !runtime ||
    !['available', 'not_installed', 'unsupported_version', 'unverified'].includes(
      String(runtime.status),
    ) ||
    typeof runtime.available !== 'boolean' ||
    (runtime.probe_available !== undefined && typeof runtime.probe_available !== 'boolean') ||
    !(runtime.version === null || typeof runtime.version === 'string')
  )
    throw new Error('ai_invalid_response');
  return value as AISettings;
}
