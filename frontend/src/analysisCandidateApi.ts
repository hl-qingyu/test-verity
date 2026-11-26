import { isRecord } from './api/guards';
import { apiRequest } from './api/http';
type Conflict = { path: string; values: string[] };
export type AnalysisCandidate = {
  candidateJson: string;
  sha256: string;
  items: {
    group: string;
    ordinal: number;
    title: string;
    rawJson: string;
    conflicts: Conflict[];
  }[];
  conflicts: Conflict[];
  parseError: boolean;
  errorCode: string;
  canEdit: boolean;
  published: boolean;
  history: {
    at: string;
    actor_id: number;
    reason: string;
    error_code: string;
    validation_passed: boolean;
  }[];
};

const record = isRecord;
function conflicts(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.every(
      (c) =>
        record(c) &&
        typeof c.path === 'string' &&
        Array.isArray(c.values) &&
        c.values.every((x) => typeof x === 'string'),
    )
  );
}
export function parseAnalysisCandidate(value: unknown): AnalysisCandidate {
  if (
    !record(value) ||
    typeof value.candidateJson !== 'string' ||
    typeof value.sha256 !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.sha256) ||
    typeof value.parseError !== 'boolean' ||
    typeof value.errorCode !== 'string' ||
    typeof value.canEdit !== 'boolean' ||
    typeof value.published !== 'boolean' ||
    !conflicts(value.conflicts) ||
    !Array.isArray(value.items) ||
    !value.items.every(
      (i) =>
        record(i) &&
        typeof i.group === 'string' &&
        Number.isSafeInteger(i.ordinal) &&
        Number(i.ordinal) > 0 &&
        typeof i.title === 'string' &&
        typeof i.rawJson === 'string' &&
        conflicts(i.conflicts),
    ) ||
    !Array.isArray(value.history) ||
    !value.history.every(
      (h) =>
        record(h) &&
        typeof h.at === 'string' &&
        Number.isFinite(Date.parse(h.at)) &&
        Number.isSafeInteger(h.actor_id) &&
        Number(h.actor_id) > 0 &&
        typeof h.reason === 'string' &&
        typeof h.error_code === 'string' &&
        typeof h.validation_passed === 'boolean',
    )
  )
    throw new Error('invalid_response');
  return value as AnalysisCandidate;
}

export async function candidateReviewRequest(endpoint: string, options: RequestInit = {}) {
  return parseAnalysisCandidate(await apiRequest<unknown>(endpoint, options));
}
