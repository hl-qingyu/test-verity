import { createGuards } from './api/guards';
import { apiRequest } from './api/http';

export type CliEvent = {
  sequence: number;
  at: string | null;
  elapsed_seconds: number | null;
  type: string;
  text: string;
  truncated: boolean;
};
export type CliEvents = {
  items: CliEvent[];
  next_cursor: number;
  has_more: boolean;
  available: boolean;
  status: string;
  attempt_index: number;
  attempts: { index: number; status: string; started_at: string | null }[];
};

const guards = createGuards('generation_response_invalid');
const object = guards.obj;

export function parseCliEvents(value: unknown): CliEvents {
  const r = object(value);
  if (
    !Array.isArray(r.items) ||
    !Array.isArray(r.attempts) ||
    !Number.isSafeInteger(r.next_cursor) ||
    Number(r.next_cursor) < 0 ||
    !Number.isSafeInteger(r.attempt_index) ||
    typeof r.has_more !== 'boolean' ||
    typeof r.available !== 'boolean' ||
    typeof r.status !== 'string'
  )
    throw Error('generation_response_invalid');
  const items = r.items.map((raw): CliEvent => {
    const e = object(raw);
    if (
      !Number.isSafeInteger(e.sequence) ||
      Number(e.sequence) < 1 ||
      !(e.at === null || typeof e.at === 'string') ||
      !(
        e.elapsed_seconds === null ||
        (typeof e.elapsed_seconds === 'number' && Number.isFinite(e.elapsed_seconds))
      ) ||
      typeof e.type !== 'string' ||
      typeof e.text !== 'string' ||
      typeof e.truncated !== 'boolean'
    )
      throw Error('generation_response_invalid');
    return {
      sequence: Number(e.sequence),
      at: e.at,
      elapsed_seconds: e.elapsed_seconds,
      type: e.type,
      text: e.text,
      truncated: e.truncated,
    };
  });
  const attempts = r.attempts.map((raw) => {
    const a = object(raw);
    if (
      !Number.isSafeInteger(a.index) ||
      Number(a.index) < 0 ||
      typeof a.status !== 'string' ||
      !(a.started_at === null || typeof a.started_at === 'string')
    )
      throw Error('generation_response_invalid');
    return { index: Number(a.index), status: a.status, started_at: a.started_at };
  });
  return {
    items,
    attempts,
    next_cursor: Number(r.next_cursor),
    has_more: r.has_more,
    available: r.available,
    status: r.status,
    attempt_index: Number(r.attempt_index),
  };
}

export async function cliEvents(
  url: string,
  cursor: number,
  signal: AbortSignal,
  attempt?: number,
) {
  const params = new URLSearchParams({ cursor: String(cursor) });
  if (attempt !== undefined) params.set('attempt', String(attempt));
  const result = parseCliEvents(await apiRequest<unknown>(`${url}?${params}`, { signal }));
  if (
    result.next_cursor !== cursor + result.items.length ||
    result.items.some((e, i) => e.sequence !== cursor + i + 1) ||
    (result.has_more && !result.items.length)
  )
    throw Error('generation_response_invalid');
  return result;
}
