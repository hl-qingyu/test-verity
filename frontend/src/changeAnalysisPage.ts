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
  can_start?: boolean;
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
function object(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('文件对象结构无效。');
  return v as Record<string, unknown>;
}
function text(v: unknown): string {
  if (typeof v !== 'string' || v.length > 1000000) throw new Error('文本字段无效或过长。');
  return v;
}
function list<T>(v: unknown, parse: (x: unknown) => T): T[] {
  if (!Array.isArray(v) || v.length > 20000) throw new Error('列表结构无效或超出本页预览容量。');
  return v.map(parse);
}
function item(v: unknown): ChangeItem {
  const o = object(v);
  const result: ChangeItem = {
    key: text(o.key),
    title: text(o.title),
    text: text(o.text),
    function: '',
    kind: '',
    cause: '',
    severity: '',
    evidence: '',
    before: '',
    after: '',
    location: '',
    directness: '',
    certainty: '',
    attribution: '',
    suggestion: '',
    verification: '',
    priority: '',
    caseRef: '',
    suggested: '',
    data: '',
    action: '',
    expected: '',
    chain: [],
    missing: [],
    change_keys: [],
  };
  if (!result.key.trim() || !result.title.trim()) throw new Error('结果编号和标题不能为空。');
  if (Object.hasOwn(Object.prototype, result.key)) throw new Error('结果编号包含保留名称。');
  for (const key of [
    'function',
    'kind',
    'cause',
    'severity',
    'evidence',
    'before',
    'after',
    'location',
    'directness',
    'certainty',
    'attribution',
    'suggestion',
    'verification',
    'priority',
    'caseRef',
    'suggested',
    'data',
    'action',
    'expected',
  ] as const) {
    if (o[key] !== undefined) result[key] = text(o[key]);
  }
  for (const key of ['chain', 'missing', 'change_keys'] as const)
    if (o[key] !== undefined) result[key] = list(o[key], text);
  if (result.cause && !Object.hasOwn(changeCauses, result.cause))
    throw new Error('风险归因不符合展示格式。');
  return result;
}
// Display compatibility with the reviewed HTML prototype, not a production Skill validator.
export function parseChangePreview(
  inputText: string,
  reportText: string,
  projectId: number,
): Omit<PageChangeRecord, 'id' | 'title' | 'createdAt'> {
  const input = object(JSON.parse(inputText.replace(/^\uFEFF/, ''))),
    report = object(JSON.parse(reportText.replace(/^\uFEFF/, '')));
  for (const data of [input, report]) {
    if (data.analysis_type !== 'CHANGE_IMPACT' || data.contract_version !== 1)
      throw new Error('当前仅支持已审阅原型的变更分析双JSON展示格式，正式契约尚未接入。');
    if (data.project_id !== undefined && data.project_id !== projectId)
      throw new Error('文件项目与当前项目不一致。');
  }
  if (!text(input.request_id) || input.request_id !== report.request_id)
    throw new Error('input.json和report.json的request_id不一致。');
  if (
    input.mode !== 'REQUIREMENT_CHANGE' &&
    input.mode !== 'CODE_CHANGE' &&
    input.mode !== 'PROTOTYPE_CHANGE'
  )
    throw new Error('变更方式无效。');
  const pairs = list(input.comparison_pairs, (v) => {
    const o = object(v);
    return {
      name: o.name === undefined ? '用户提供的比较组' : text(o.name),
      before: text(o.before),
      after: text(o.after),
      update: o.update === undefined ? '用户提供的比较范围' : text(o.update),
      scope: list(o.scope, text),
    };
  });
  if (!pairs.length || pairs.some((p) => !p.before || !p.after || !p.scope.length))
    throw new Error('缺少新旧固定版本或比较范围。');
  const changes = list(report.changes, item),
    impacts = list(report.risks, item),
    regressions = list(report.regression_scope, item);
  const keys = [...changes, ...impacts, ...regressions].map((x) => x.key);
  if (new Set(keys).size !== keys.length) throw new Error('结果编号重复，无法准确定位处理和追问。');
  const changeKeys = new Set(changes.map((x) => x.key));
  if ([...impacts, ...regressions].some((x) => x.change_keys.some((key) => !changeKeys.has(key))))
    throw new Error('影响或回归引用了不存在的变化项。');
  return {
    projectId,
    mode: input.mode,
    origin: 'PREVIEW',
    pairs,
    targets: list(input.targets, (v) => text(object(v).name)),
    context: list(input.context, text),
    focus: input.focus === undefined ? '' : text(input.focus),
    changes,
    impacts,
    regressions,
    handling: {},
    chatDraft: '',
    inputText,
    reportText,
  };
}
export function changeMarkdown(record: PageChangeRecord) {
  return (
    `# ${record.title}\n\n${record.origin === 'DRAFT' ? '待接入：范围草稿，尚无分析结果' : '本页导入预览：未经正式证据校验'}\n页面暂存，不代表项目共享或已执行测试。\n\n` +
    record.pairs
      .map(
        (p) =>
          `## ${p.name}\n旧：${p.before}\n新：${p.after}\n${p.update}\n${p.scope.join('\n')}\n`,
      )
      .join('\n') +
    `\n## 固定引用\n${record.context.join('\n')}\n\n关注点：${record.focus}\n` +
    (Object.keys(changeTabs) as ChangeTab[])
      .map(
        (tab) =>
          `\n## ${changeTabs[tab]}\n` +
          changeItems(record, tab)
            .map(
              (x) =>
                `\n### ${x.key} · ${x.title}\n${x.text}\n${x.kind} ${x.cause} ${x.severity} ${x.evidence}\n旧证据：${x.before}\n新证据：${x.after}\n${x.location}\n${x.attribution}\n${x.chain.join(' → ')}\n${x.missing.join('\n')}\n建议：${x.suggestion}\n验证：${x.verification}\n${x.priority} ${x.caseRef} ${x.suggested}\n前置：${x.data}\n操作：${x.action}\n应核对：${x.expected}\n本页处理：${(record.handling[x.key] || []).map((h) => `${h.time} ${h.status} ${h.note}`).join('\n')}\n`,
            )
            .join(''),
      )
      .join('\n') +
    '\n增量补充未提及的旧规则继续适用，不逐条列出。采纳回归建议不表示已执行，旧问题不自动关闭。\n'
  );
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
