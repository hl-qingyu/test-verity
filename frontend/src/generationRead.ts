import { apiRequest } from './api/http';
import { parseCaseList } from './caseApi';
import type { CaseList } from './caseApi';

export async function generationCaseSnapshot(
  projectId: number,
  signal: AbortSignal,
  includeRetired = false,
): Promise<CaseList> {
  const value = parseCaseList(
    await apiRequest<unknown>(`/api/projects/${projectId}/cases/edit-scope`, {
      method: 'POST',
      signal,
      body: JSON.stringify({
        page: 1,
        page_size: 100,
        category_id: null,
        conditions: [],
        lifecycle: includeRetired ? 'ALL' : 'ACTIVE',
      }),
    }),
  );
  if (
    value.items.length !== value.total ||
    new Set(value.items.map((c) => c.id)).size !== value.items.length
  )
    throw Error('case_response_invalid');
  return value;
}
