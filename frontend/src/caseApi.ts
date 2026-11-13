import { apiErrorMessage, apiRequest } from './api/http';

export const CASE_COLUMNS = [
  ['serial', '序号'],
  ['number', '用例编号'],
  ['module', '功能模块'],
  ['structure', '功能结构'],
  ['case_type', '用例类型'],
  ['priority', '优先级'],
  ['description', '用例描述'],
  ['title', '验证用例子项'],
  ['preconditions', '前置条件'],
  ['steps', '操作步骤'],
  ['expected', '预期结果'],
  ['result', '测试结果'],
  ['tester', '测试人员'],
  ['remark', '备注'],
] as const;
export const CASE_TYPES = [
  '',
  '功能需求',
  '业务流程',
  '逻辑校验',
  '异常用例',
  '边界用例',
  '兼容性用例',
];
export const PRIORITIES = ['', 'P0', 'P1', 'P2', 'P3', 'P4'];
export const CASE_RESULTS = ['', '未测', '通过', '失败', '阻塞', '跳过', '废弃'];
export const DESIGN_FIELDS = [
  'module',
  'structure',
  'case_type',
  'priority',
  'description',
  'title',
  'preconditions',
  'steps',
  'expected',
  'remark',
  'data_requirements',
  'cleanup',
] as const;
export type Design = Record<(typeof DESIGN_FIELDS)[number], string>;
export type CaseCategory = { id: number; name: string; count: number };
export type CaseMetadata = { revision: number; next_number: number; categories: CaseCategory[] };
export type CaseRow = Design & {
  lifecycle?: 'ACTIVE' | 'RETIRED';
  id: number;
  number: string;
  category_id: number | null;
  version_id: number;
  version: number;
  serial: number;
  result: string;
  tester: string;
  review_status: string;
  result_origin: string;
  source_kind: string;
};
export type CaseList = CaseMetadata & {
  items: CaseRow[];
  total: number;
  page: number;
  page_size: number;
};
export type CaseRecord = {
  id: number;
  kind: 'TEST' | 'REVIEW';
  result: string;
  tester: string;
  review_status: string;
  source_kind: string;
  recorded_by: string;
  recorded_at: string;
};
export type CaseVersion = Design & {
  id: number;
  number: number;
  source_kind: string;
  source: Record<string, string | number>;
  import_id: number | null;
  created_by: string;
  created_at: string;
  records: CaseRecord[];
};
export type CaseDetail = CaseMetadata & {
  lifecycle?: 'ACTIVE' | 'RETIRED';
  lifecycle_history?: {
    lifecycle: string;
    reason: string;
    actor_id: number;
    at: string;
    basis: Record<string, unknown>;
  }[];
  id: number;
  number: string;
  category_id: number | null;
  versions: CaseVersion[];
};
export type Condition = {
  field: (typeof CASE_COLUMNS)[number][0];
  operator: 'contains' | 'equals' | 'notContains';
  value: string;
};
export type CaseSearch = {
  lifecycle?: 'ACTIVE' | 'RETIRED' | 'ALL';
  page: number;
  page_size: 10 | 20 | 50 | 100;
  category_id: number | null;
  conditions: Condition[];
};
export type CaseEditScope = CaseSearch & { case_ids?: number[] };
export const blankDesign = (): Design =>
  Object.fromEntries(DESIGN_FIELDS.map((f) => [f, ''])) as Design;
const obj = (x: unknown): x is Record<string, unknown> => x !== null && typeof x === 'object';
const integer = (x: unknown): x is number =>
  typeof x === 'number' && Number.isSafeInteger(x) && x >= 0;
const fail = () => {
  throw new Error('case_response_invalid');
};
const strings = (x: Record<string, unknown>, fields: readonly string[]) =>
  fields.every((f) => typeof x[f] === 'string');
export function parseCaseMetadata(x: unknown): CaseMetadata {
  if (!obj(x) || !integer(x.revision) || !integer(x.next_number) || !Array.isArray(x.categories))
    return fail();
  for (const c of x.categories)
    if (!obj(c) || !integer(c.id) || typeof c.name !== 'string' || !integer(c.count)) return fail();
  return x as CaseMetadata;
}
export function parseCaseList(x: unknown): CaseList {
  parseCaseMetadata(x);
  if (
    !obj(x) ||
    !Array.isArray(x.items) ||
    !integer(x.total) ||
    !integer(x.page) ||
    !integer(x.page_size)
  )
    return fail();
  for (const row of x.items)
    if (
      !obj(row) ||
      (row.lifecycle !== undefined && !['ACTIVE', 'RETIRED'].includes(String(row.lifecycle))) ||
      !['id', 'version_id', 'version', 'serial'].every((f) => integer(row[f])) ||
      (row.category_id !== null && !integer(row.category_id)) ||
      !strings(row, [
        'number',
        ...DESIGN_FIELDS,
        'result',
        'tester',
        'review_status',
        'result_origin',
        'source_kind',
      ])
    )
      return fail();
  return x as CaseList;
}
export function parseCaseDetail(x: unknown): CaseDetail {
  parseCaseMetadata(x);
  if (
    !obj(x) ||
    !integer(x.id) ||
    typeof x.number !== 'string' ||
    (x.category_id !== null && !integer(x.category_id)) ||
    !Array.isArray(x.versions) ||
    !x.versions.length
  )
    return fail();
  for (const v of x.versions) {
    if (
      !obj(v) ||
      !integer(v.id) ||
      !integer(v.number) ||
      !strings(v, [...DESIGN_FIELDS, 'source_kind', 'created_by', 'created_at']) ||
      !obj(v.source) ||
      (v.import_id !== null && !integer(v.import_id)) ||
      !Array.isArray(v.records)
    )
      return fail();
    for (const r of v.records)
      if (
        !obj(r) ||
        !integer(r.id) ||
        !['TEST', 'REVIEW'].includes(String(r.kind)) ||
        !strings(r, [
          'result',
          'tester',
          'review_status',
          'source_kind',
          'recorded_by',
          'recorded_at',
        ])
      )
        return fail();
  }
  return x as CaseDetail;
}
export async function caseListRequest(base: string, search: CaseSearch, signal?: AbortSignal) {
  return parseCaseList(
    await apiRequest<unknown>(`${base}/search`, {
      method: 'POST',
      body: JSON.stringify(search),
      signal,
    }),
  );
}
export function caseError(e: unknown, onSessionEnd: () => void) {
  return apiErrorMessage(e, onSessionEnd, {
    case_selection_changed: '所选用例已删除、不可访问或不在此范围，请重新勾选；未保存任何修改。',
    case_edit_limit: '批量范围超过20,000条或50MB，请缩小筛选范围；没有保存任何修改。',
    cases_changed: '项目用例已更新，请刷新后重新核对再提交。',
    case_not_found: '用例不存在或没有项目权限。',
    project_not_found: '项目不存在或你已无访问权限。',
    case_category_not_found: '分类不存在，请重新加载。',
    case_create_conflict: '此创建请求已保存过其他内容，请关闭弹窗并刷新核对。',
    case_category_duplicate: '分类名称已存在。',
    case_category_target_required: '该分类有关联用例，请选择其他有效分类。',
    invalid_request: '字段格式不正确，请检查名称、枚举或内容长度。',
    case_response_invalid: '返回数据异常，请重新加载。',
    case_import_format: '导入仅支持XLSX、XLS、CSV。',
    case_import_invalid: '文件无法解析，请检查文件是否损坏、加密或CSV格式不完整。',
    case_import_limit: '超出单批解析范围，请拆分文件后导入；不会部分入库。',
    document_empty: '不能导入空文件。',
    document_text_encoding: '文件编码无法识别，请转为UTF-8后重试。',
    document_expansion_limit: '文件展开内容过大，无法安全解析。',
    document_storage_unavailable: '原件存储暂不可用。',
    case_import_not_found: '导入批次不存在或没有项目权限。',
    case_import_sheet: '请选择有效工作表。',
    case_import_header: '请选择有效表头行。',
    case_import_mapping_empty: '请至少映射一个业务字段，序号和编号不参与入库。',
    case_import_has_errors: '文件校验未通过，请修改原文件后重新上传。',
    case_import_duplicate_decisions: '请先确认重复用例的处理方式。',
    case_preview_changed: '导入预览已变化，请重新检查文件。',
    case_import_committed: '此批次已入库，不能修改。',
    case_import_conflict: '相同上传请求对应的文件不同，请重新选择文件。',
  });
}

export type CaseImportInfo = {
  id: number;
  filename: string;
  preview_revision: number;
  committed: boolean;
};
type ImportIssue = { sheet: string; row: number; field: string; message: string };
export type CaseImportItem = {
  key: string;
  sheet: string;
  row: number;
  values: Record<string, string>;
  matches: CaseRow[];
  match_count: number;
};
export type CaseImportPreview = {
  preview_revision: number;
  revision: number;
  total: number;
  skipped: number;
  duplicate_count: number;
  errors: ImportIssue[];
  warnings: ImportIssue[];
  sheets: { name: string; header_row: number }[];
  items: CaseImportItem[];
};
export function parseCaseImportInfo(x: unknown): CaseImportInfo {
  if (
    !obj(x) ||
    !integer(x.id) ||
    typeof x.filename !== 'string' ||
    !integer(x.preview_revision) ||
    typeof x.committed !== 'boolean'
  )
    return fail();
  return x as CaseImportInfo;
}
export function parseCaseImportPreview(x: unknown): CaseImportPreview {
  if (
    !obj(x) ||
    !['preview_revision', 'revision', 'total', 'skipped', 'duplicate_count'].every((k) =>
      integer(x[k]),
    ) ||
    !Array.isArray(x.items) ||
    !Array.isArray(x.errors) ||
    !Array.isArray(x.warnings) ||
    !Array.isArray(x.sheets)
  )
    return fail();
  if (
    ![...x.errors, ...x.warnings].every(
      (i) => obj(i) && integer(i.row) && strings(i, ['sheet', 'field', 'message']),
    )
  )
    return fail();
  if (!x.sheets.every((i) => obj(i) && typeof i.name === 'string' && integer(i.header_row)))
    return fail();
  for (const item of x.items) {
    if (
      !obj(item) ||
      typeof item.key !== 'string' ||
      typeof item.sheet !== 'string' ||
      !integer(item.row) ||
      !integer(item.match_count) ||
      !obj(item.values) ||
      !Object.values(item.values).every((v) => typeof v === 'string') ||
      !Array.isArray(item.matches)
    )
      return fail();
    for (const row of item.matches)
      if (
        !obj(row) ||
        !integer(row.id) ||
        typeof row.number !== 'string' ||
        !integer(row.version_id) ||
        (row.category_id !== null && !integer(row.category_id)) ||
        !strings(row, [...DESIGN_FIELDS, 'result', 'tester'])
      )
        return fail();
  }
  return x as CaseImportPreview;
}

export type EditableField = Exclude<(typeof CASE_COLUMNS)[number][0], 'serial' | 'number'>;
export type CaseChanges = Partial<Record<EditableField, string>>;
export function caseChanges(original: CaseRow, edited: CaseRow): CaseChanges {
  const changes: CaseChanges = {};
  for (const [key] of CASE_COLUMNS) {
    if (key !== 'serial' && key !== 'number' && original[key] !== edited[key])
      changes[key] = edited[key];
  }
  return changes;
}
export function parseBatchResult(value: unknown) {
  const meta = parseCaseMetadata(value);
  if (!obj(value) || !integer(value.updated)) return fail();
  return { ...meta, updated: value.updated };
}
