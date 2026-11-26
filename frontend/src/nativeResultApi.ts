import { createGuards } from './api/guards';
import { apiRequest } from './api/http';

export type NativeResult = {
  saved?: boolean;
  saved_batch_id?: number | null;
  id: string;
  timestamp: string;
  case_count: number;
  note_count: number;
  complete: boolean | null;
};
export type NativeResultPreview = {
  saved?: boolean;
  saved_batch_id?: number | null;
  id: string;
  raw_json: string;
  valid_cases: number;
  issues: number;
  can_save: boolean;
};
const guards = createGuards('generation_response_invalid');
const object = guards.obj;

const count = (value: unknown) => guards.int(value, 0);
const identity = guards.hash64;
export async function nativeResults(base: string, signal: AbortSignal): Promise<NativeResult[]> {
  const response = object(await apiRequest<unknown>(`${base}/results`, { signal }));
  if (!Array.isArray(response.items)) throw Error('generation_response_invalid');
  const items = response.items.map((value) => {
    const item = object(value);
    if (item.saved !== undefined && typeof item.saved !== 'boolean')
      throw Error('generation_response_invalid');
    if (
      typeof item.timestamp !== 'string' ||
      !Number.isFinite(Date.parse(item.timestamp)) ||
      (item.complete !== null && typeof item.complete !== 'boolean')
    )
      throw Error('generation_response_invalid');
    return {
      saved: item.saved === undefined ? false : item.saved === true,
      saved_batch_id: item.saved_batch_id == null ? null : count(item.saved_batch_id),
      id: identity(item.id),
      timestamp: item.timestamp,
      case_count: count(item.case_count),
      note_count: count(item.note_count),
      complete: item.complete as boolean | null,
    };
  });
  if (new Set(items.map((item) => item.id)).size !== items.length)
    throw Error('generation_response_invalid');
  return items;
}
export async function nativeResultPreview(
  base: string,
  id: string,
  signal: AbortSignal,
): Promise<NativeResultPreview> {
  const item = object(await apiRequest<unknown>(`${base}/results/${identity(id)}`, { signal }));
  if (item.saved !== undefined && typeof item.saved !== 'boolean')
    throw Error('generation_response_invalid');
  if (
    identity(item.id) !== id ||
    typeof item.raw_json !== 'string' ||
    typeof item.can_save !== 'boolean'
  )
    throw Error('generation_response_invalid');
  return {
    saved: item.saved === undefined ? false : item.saved === true,
    saved_batch_id: item.saved_batch_id == null ? null : count(item.saved_batch_id),
    id,
    raw_json: item.raw_json,
    valid_cases: count(item.valid_cases),
    issues: count(item.issues),
    can_save: item.can_save,
  };
}
