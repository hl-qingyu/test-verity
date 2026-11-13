import { apiErrorMessage, apiRequest } from './api/http';

export const overviewModules = {
  requirements: ['需求分析', '/requirements', 'spark'],
  generate: ['用例生成', '/generate', 'list'],
  coverage: ['用例分析', '/coverage', 'chart'],
  code: ['代码分析', '/code', 'code'],
  changes: ['变更分析', '/changes', 'branch'],
} as const;
export type OverviewModule = keyof typeof overviewModules;
export const overviewFilters = {
  all: '全部',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
};
export type OverviewFilter = keyof typeof overviewFilters;
export type OverviewRecord = {
  module: OverviewModule;
  record_type: 'run' | 'task' | 'report';
  record_id: number;
  title: string;
  status: string;
  created_at: string;
  actor: string;
  imported: boolean;
  outcome: string | null;
  application_failed: boolean;
};
export type AttentionPart = { group: string; state: string; label: string; count: number | null };
export type OverviewSummary = {
  project_id: number;
  project: { name: string; identifier: string; description: string };
  as_of: string;
  filter: OverviewFilter;
  counts: {
    requirements: number;
    prototypes: number;
    cases: number;
    queued: number | null;
    running: number | null;
  };
  attention: { module: OverviewModule; available: boolean; parts: AttentionPart[] }[];
  recent: OverviewRecord[];
  unavailable: OverviewModule[];
};
export type AttentionPage = {
  project_id: number;
  module: OverviewModule;
  group: string;
  state: string;
  page: number;
  total: number;
  items: OverviewRecord[];
};
const statuses = ['PREPARED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'];
export const overviewStates: Record<string, string> = {
  PREPARED: '待开始',
  QUEUED: '排队中',
  RUNNING: '分析中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};
function obj(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw Error('overview_response_invalid');
  return value as Record<string, unknown>;
}
function count(value: unknown, nullable = false) {
  if (nullable && value === null) return;
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw Error('overview_response_invalid');
}
export function parseOverviewRecord(value: unknown): OverviewRecord {
  const r = obj(value);
  if (
    !Object.hasOwn(overviewModules, String(r.module)) ||
    !statuses.includes(String(r.status)) ||
    !['run', 'task', 'report'].includes(String(r.record_type))
  )
    throw Error('overview_response_invalid');
  if (!Number.isSafeInteger(r.record_id) || Number(r.record_id) < 1)
    throw Error('overview_response_invalid');
  if (
    (['generate', 'coverage'].includes(String(r.module)) && r.record_type !== 'run') ||
    (['code', 'changes'].includes(String(r.module)) && r.record_type !== 'task') ||
    (r.module === 'requirements' && !['task', 'report'].includes(String(r.record_type)))
  )
    throw Error('overview_response_invalid');
  for (const key of ['title', 'created_at', 'actor'])
    if (typeof r[key] !== 'string') throw Error('overview_response_invalid');
  if (
    !Number.isFinite(Date.parse(String(r.created_at))) ||
    typeof r.imported !== 'boolean' ||
    typeof r.application_failed !== 'boolean' ||
    (r.outcome !== null && !['COMPLETE', 'PARTIAL', 'BLOCKED'].includes(String(r.outcome)))
  )
    throw Error('overview_response_invalid');
  return r as OverviewRecord;
}
export function parseOverview(
  value: unknown,
  projectId: number,
  filter: OverviewFilter,
): OverviewSummary {
  const r = obj(value),
    project = obj(r.project),
    counts = obj(r.counts);
  if (
    r.project_id !== projectId ||
    r.filter !== filter ||
    typeof r.as_of !== 'string' ||
    !Number.isFinite(Date.parse(r.as_of))
  )
    throw Error('overview_response_invalid');
  for (const key of ['name', 'identifier', 'description'])
    if (typeof project[key] !== 'string') throw Error('overview_response_invalid');
  for (const key of ['requirements', 'prototypes', 'cases']) count(counts[key]);
  for (const key of ['queued', 'running']) count(counts[key], true);
  if (
    !Array.isArray(r.recent) ||
    r.recent.length > 8 ||
    !Array.isArray(r.attention) ||
    r.attention.length !== 5 ||
    !Array.isArray(r.unavailable)
  )
    throw Error('overview_response_invalid');
  r.recent.forEach(parseOverviewRecord);
  const modules = new Set<string>();
  for (const value of r.attention) {
    const group = obj(value);
    if (
      !Object.hasOwn(overviewModules, String(group.module)) ||
      modules.has(String(group.module)) ||
      typeof group.available !== 'boolean' ||
      !Array.isArray(group.parts)
    )
      throw Error('overview_response_invalid');
    modules.add(String(group.module));
    for (const v of group.parts) {
      const part = obj(v);
      for (const k of ['group', 'state', 'label'])
        if (typeof part[k] !== 'string' || !part[k]) throw Error('overview_response_invalid');
      count(part.count, !group.available);
      if (!group.available && part.count !== null) throw Error('overview_response_invalid');
    }
  }
  for (const module of r.unavailable)
    if (!Object.hasOwn(overviewModules, String(module))) throw Error('overview_response_invalid');
  if (
    (r.unavailable.length > 0 && (counts.queued !== null || counts.running !== null)) ||
    (r.unavailable.length === 0 && (counts.queued === null || counts.running === null))
  )
    throw Error('overview_response_invalid');
  return r as OverviewSummary;
}
export function readOverview(project: number, filter: OverviewFilter, signal: AbortSignal) {
  return apiRequest(`/api/projects/${project}/overview?filter=${filter}`, { signal }).then(
    (value) => parseOverview(value, project, filter),
  );
}
export async function readAttention(
  project: number,
  module: OverviewModule,
  part: AttentionPart,
  page: number,
  signal: AbortSignal,
): Promise<AttentionPage> {
  const query = new URLSearchParams({
    module,
    group: part.group,
    state: part.state,
    page: String(page),
  });
  const r = obj(
    await apiRequest(`/api/projects/${project}/overview/attention?${query}`, { signal }),
  );
  if (
    r.project_id !== project ||
    r.module !== module ||
    r.group !== part.group ||
    r.state !== part.state ||
    r.page !== page ||
    !Array.isArray(r.items) ||
    r.items.length > 20
  )
    throw Error('overview_response_invalid');
  count(r.total);
  r.items.forEach((value) => {
    if (parseOverviewRecord(value).module !== module) throw Error('overview_response_invalid');
  });
  return r as AttentionPage;
}
export function overviewHref(projectId: number, record: OverviewRecord, part?: AttentionPart) {
  const query = new URLSearchParams({
    overview: '1',
    project: String(projectId),
    record: String(record.record_id),
    record_type: record.record_type,
  });
  if (part) {
    query.set('group', part.group);
    query.set('state', part.state);
  }
  return `${overviewModules[record.module][1]}?${query}`;
}
export const overviewError = (error: unknown, end: () => void) =>
  apiErrorMessage(error, end, {
    project_not_found: '项目不存在或已无访问权限。',
    overview_response_invalid: '概览数据格式异常，请重新读取。',
    overview_module_unavailable: '该模块摘要暂时不可用，请稍后重试。',
    overview_filter_invalid: '筛选条件已失效，请刷新概览。',
  });
