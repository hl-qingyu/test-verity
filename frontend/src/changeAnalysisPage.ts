export const changeModes = {
  REQUIREMENT_CHANGE: '需求变更',
  CODE_CHANGE: '代码变更',
  PROTOTYPE_CHANGE: '原型变更',
} as const;
export type ChangeMode = keyof typeof changeModes;
export const changeTabs = {
  changes: '变化项',
  impacts: '影响与风险',
  regressions: '回归建议',
} as const;
export type ChangeTab = keyof typeof changeTabs;
export const changeCauses = {
  introduced: '本次引入',
  pre_existing: '原有问题',
  unknown: '无法归因',
} as const;
export type ChangeItem = {
  key: string;
  title: string;
  text: string;
  function: string;
  kind: string;
  cause: string;
  severity: string;
  evidence: string;
  before: string;
  after: string;
  location: string;
  directness: string;
  certainty: string;
  attribution: string;
  suggestion: string;
  verification: string;
  chain: string[];
  missing: string[];
  change_keys: string[];
  priority: string;
  caseRef: string;
  suggested: string;
  data: string;
  action: string;
  expected: string;
  details?: { label: string; text: string }[];
};
export type ChangePair = {
  name: string;
  before: string;
  after: string;
  update: string;
  scope: string[];
  kind?: string;
  targetFiles?: number;
  selection?: ChangeSelection;
};
export type LocalChangeSnapshot = {
  ref: string;
  captured_at: string;
  scope: string[];
  files: { path: string; content: string; sha256: string }[];
  skipped: Record<string, string>;
};
export type ChangeSelection = {
  kind:
    | 'FILE'
    | 'DIRECTORY_PROTOTYPE'
    | 'GITHUB_CODE'
    | 'LOCAL_CODE'
    | 'GITHUB_PROTOTYPE'
    | 'LINK_PROTOTYPE';
  source_id: number;
  update_mode: 'FULL_REPLACEMENT' | 'INCREMENTAL_SUPPLEMENT' | 'CODE_SNAPSHOT';
  source_version?: number;
  connection_id?: number;
  before_ref?: string;
  after_ref?: string;
  paths?: string[];
  before_version_id?: number;
  after_version_id?: number;
  after_document_id?: number;
  baseline_report_id?: number;
  snapshot?: string;
  url?: string;
  before_local?: LocalChangeSnapshot;
  after_local?: LocalChangeSnapshot;
};
export type ChangeHandling = { status: string; note: string; time: string };
export type PageChangeRecord = {
  ai?: unknown;
  batches?: {
    version?: number;
    total: number;
    completed: number;
    failed: number;
    planned_calls?: number;
    remaining_calls?: number;
    review_batches?: number;
    batches: {
      id: number;
      status: string;
      error_code: string;
      input_bytes: number;
      files: string[];
      kind?: 'ANALYSIS' | 'INTEGRATION';
      depends_on?: number[];
      blocked_targets?: string[];
      blocking_reason?: string;
      oversized?: boolean;
      callable?: boolean;
    }[];
  };
  actorId?: number;
  id: string;
  projectId: number;
  title: string;
  mode: ChangeMode;
  createdAt: string;
  origin: 'DRAFT' | 'PREVIEW' | 'AI' | 'IMPORT';
  pairs: ChangePair[];
  targets: string[];
  context: string[];
  focus: string;
  changes: ChangeItem[];
  impacts: ChangeItem[];
  regressions: ChangeItem[];
  handling: Record<string, ChangeHandling[]>;
  chatDraft: string;
  inputText?: string;
  reportText?: string;
  status?: string;
  revision?: number;
  error_code?: string;
  can_cancel?: boolean;
  terminal_available?: boolean;
  can_retry?: boolean;
  retry_preparation?: boolean;
  retry_replan?: boolean;
  can_revalidate?: boolean;
  candidate_available?: boolean;
  outcome?: string;
  targetResults?: { name: string; status: string; note: string }[];
  limitations?: string[];
  summary?: string;
  structured?: Record<string, unknown>;
  updatedAt?: string;
  loaded?: boolean;
};
export function changeItems(record: PageChangeRecord, tab: ChangeTab) {
  return record[tab].filter(
    (x) => tab !== 'changes' || !['旧规则保留', '未变规则', 'UNCHANGED'].includes(x.kind),
  );
}
export function changeScopeError(
  mode: ChangeMode,
  pairs: ChangePair[],
  targets: string[],
  confirmed: boolean,
  hasMaterials: boolean,
  contextKinds: { kind: string; targetFiles: number }[] = [],
) {
  if (!targets.length) return '请至少选择一个分析目标。';
  if (!pairs.length || pairs.some((p) => !p.before || !p.after || !p.scope.length))
    return '请选择实际可用的新旧固定版本和范围。';
  if (pairs.some((p) => p.before === p.after))
    return '新旧版本相同，请选择不同基准；无差异不创建记录。';
  if (!confirmed) return '请核对并确认新旧范围对应关系。';
  if (mode === 'CODE_CHANGE') {
    const roles = new Set(
      [...pairs, ...contextKinds].filter((p) => (p.targetFiles || 0) > 0).map((p) => p.kind),
    );
    if (
      targets.includes('前后端一致性') &&
      (!roles.has('BACKEND') || (!roles.has('WEB') && !roles.has('FLUTTER')))
    )
      return '前后端一致性必须实际选择目标侧后端和前端／移动端文件，缺一端拦截整次创建。';
    if (targets.length === 1 && targets[0] === '需求符合性' && !hasMaterials)
      return '需求符合性需要固定版本需求或原型依据。';
  }
  return '';
}
export function downloadChange(name: string, content: string, json = false) {
  const url = URL.createObjectURL(
    new Blob([content], {
      type: json ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8',
    }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
