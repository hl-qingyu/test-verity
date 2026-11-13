import { callModeName } from './aiConfiguration';

export function AIConfigurationSummary({ value }: { value: unknown }) {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (typeof row.name !== 'string' || typeof row.model !== 'string') return null;
  return (
    <span className="hint">
      {callModeName(typeof row.call_mode === 'string' ? row.call_mode : undefined)} · {row.name} ·{' '}
      {row.model}
    </span>
  );
}
