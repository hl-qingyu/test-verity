import { deletionErrors } from './analysisDeletionApi';
import { apiRequest } from './api/http';
import { codeError } from './codeAnalysisApi';
import { snapshotTime } from './snapshotTime';
import { changeModes } from './changeAnalysisPage';
import type { ChangeItem, ChangeMode, PageChangeRecord } from './changeAnalysisPage';

export const changeStates: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '分析中',
  PREPARED: '待开始',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};
export const changeTargets: Record<string, string> = {
  BUSINESS_IMPACT: '业务变化与功能影响',
  IMPLEMENTATION_FOLLOWUP: '代码实现跟进',
  CASE_REGRESSION: '用例维护与回归建议',
  BUG: '代码Bug',
  REQUIREMENT_DEVIATION: '需求符合性',
  FRONTEND_BACKEND_MISMATCH: '前后端一致性',
};
export const handlingStates: Record<string, string> = {
  PENDING: '待处理',
  CONFIRMED: '已确认',
  RESOLVED: '已处理',
  FALSE_POSITIVE: '误报',
  NEEDS_EVIDENCE: '需补充证据',
  ACCEPTED: '采纳',
  DEFERRED: '暂缓',
  REJECTED: '不采纳',
};
export const changeErrors: Record<string, string> = {
  change_full_input_required:
    '此记录属于历史分批流程，请点击完整输入重新分析，使用固定资料发起一次新的AI请求。',
  change_batch_replan_required: '此记录使用历史分组，请点击完整输入重新分析，原记录和成果保留。',
  change_batches_failed: '历史分批中有未完成项；原成果已保留，可使用完整固定输入重新分析。',
  change_batch_snapshot_mismatch: '分批计划与固定输入不一致，已停止调用，请核对记录。',
  change_batch_start_invalid: '当前记录不处于待开始状态，请刷新记录。',
  change_batch_start_owner_only: '仅此任务发起人可以开始分批分析。',
  change_batch_dependencies_pending: '历史前置批次未完成，当时未调用本批AI；原记录保留。',
  change_batch_pairing_unavailable:
    '未找到可核对的实际接口配对，本目标未调用AI；请补充对应实现或消费端依据。',
  ...deletionErrors,
  change_request_invalid: '新建或导入请求的字段、类型或范围信息不符合要求，请核对后重试。',
  change_json_invalid: '请求JSON编码无效，请重新提交。',
  change_contract_invalid: '结果结构或JSON不符合变更分析契约。',
  change_evidence_invalid: '证据、侧别、引用或覆盖校验失败，可下载原始候选核对。',
  change_both_sides_required: '前后端一致性必须提供目标侧双方实际代码。',
  change_bindings_required: '请为每份固定快照选择当前项目对应来源。',
  change_binding_mismatch: '原件绑定与快照类型、版本或登记角色不一致。',
  change_project_mismatch: '双JSON的项目与当前项目不一致。',
  change_retry_requires_new_scope: '此前未完整固定双侧输入，请重新核对范围后新建分析。',
  change_retry_scope_unavailable: '原记录缺少完整选择或Skill快照，请重新核对范围后新建分析。',
  github_connection_failed: '读取GitHub源码时连接失败，可点击重试。',
  change_input_too_large: '此历史任务触发旧版输入限制；新建变更分析已移除合计字节门槛。',
  change_source_storage_unavailable: '固定代码正文无法读取或保存，请检查后端存储后重新准备。',
  change_handling_changed: '处理状态已被更新，请刷新记录后重试。',
  change_worker_interrupted: 'Worker中断，未自动重发计费请求，可人工重试。',
  change_chat_busy: '本记录有对话处理中，请等待或取消。',
  change_no_changes: '所选范围没有可分析变化，未调用AI。',
};
export function changeError(e: unknown, end: () => void) {
  return e instanceof Error && Object.hasOwn(changeErrors, e.message)
    ? changeErrors[e.message]
    : codeError(e, end);
}
export function object(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw Error('change_response_invalid');
  return v as Record<string, unknown>;
}
export function string(v: unknown): string {
  if (typeof v !== 'string') throw Error('change_response_invalid');
  return v;
}
function number(v: unknown): number {
  if (!Number.isSafeInteger(v) || Number(v) <= 0) throw Error('change_response_invalid');
  return Number(v);
}
export function array(v: unknown): unknown[] {
  if (!Array.isArray(v)) throw Error('change_response_invalid');
  return v;
}
function optional(v: unknown): string {
  return v === undefined || v === null ? '' : string(v);
}
function strings(v: unknown): string[] {
  return v === undefined ? [] : array(v).map(string);
}
function values(v: unknown): Record<string, unknown>[] {
  return v === undefined ? [] : array(v).map(object);
}

function batches(value: unknown): PageChangeRecord['batches'] {
  if (value === undefined || value === null) return undefined;
  const v = object(value);
  const count = (n: unknown) => {
    if (!Number.isSafeInteger(n) || Number(n) < 0) throw Error('change_response_invalid');
    return Number(n);
  };
  const optionalCount = (n: unknown) => (n == null ? undefined : count(n));
  const optionalBoolean = (v: unknown) => {
    if (v == null) return undefined;
    if (typeof v !== 'boolean') throw Error('change_response_invalid');
    return v;
  };
  const rows = array(v.batches).map((item) => {
    const b = object(item);
    if (!['QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'].includes(string(b.status)))
      throw Error('change_response_invalid');
    if (b.kind != null && b.kind !== 'ANALYSIS' && b.kind !== 'INTEGRATION')
      throw Error('change_response_invalid');
    const dependencies = b.depends_on == null ? [] : array(b.depends_on).map(number);
    const targets = b.blocked_targets == null ? [] : strings(b.blocked_targets);
    if (
      new Set(dependencies).size !== dependencies.length ||
      new Set(targets).size !== targets.length ||
      targets.some((t) => !Object.hasOwn(changeTargets, t))
    )
      throw Error('change_response_invalid');
    return {
      id: number(b.id),
      status: string(b.status),
      error_code: string(b.error_code),
      input_bytes: count(b.input_bytes),
      files: strings(b.files),
      kind: b.kind == null ? undefined : (b.kind as 'ANALYSIS' | 'INTEGRATION'),
      depends_on: dependencies,
      blocked_targets: targets,
      blocking_reason: optional(b.blocking_reason),
      oversized: optionalBoolean(b.oversized),
      callable: optionalBoolean(b.callable),
    };
  });
  const result = {
    version: optionalCount(v.version),
    total: count(v.total),
    completed: count(v.completed),
    failed: count(v.failed),
    planned_calls: optionalCount(v.planned_calls),
    remaining_calls: optionalCount(v.remaining_calls),
    review_batches: optionalCount(v.review_batches),
    batches: rows,
  };
  if (
    result.total !== rows.length ||
    new Set(rows.map((b) => b.id)).size !== rows.length ||
    result.completed !== rows.filter((b) => b.status === 'COMPLETED').length ||
    result.failed !== rows.filter((b) => b.status === 'FAILED').length
  )
    throw Error('change_response_invalid');
  const ids = new Set(rows.map((b) => b.id));
  if (
    (result.version !== undefined && ![1, 2].includes(result.version)) ||
    rows.some((b) => b.depends_on.some((id) => !ids.has(id) || id === b.id)) ||
    (result.planned_calls !== undefined &&
      result.planned_calls !== rows.filter((b) => b.callable !== false).length) ||
    (result.remaining_calls !== undefined &&
      result.remaining_calls !==
        rows.filter((b) => b.callable !== false && b.status !== 'COMPLETED').length) ||
    (result.review_batches !== undefined &&
      result.review_batches !== rows.filter((b) => b.kind === 'INTEGRATION').length)
  )
    throw Error('change_response_invalid');
  return result;
}
const labels: Record<string, string> = {
  ADD: '新增',
  MODIFY: '修改',
  REMOVE: '删除',
  RENAME: '重命名',
  SPLIT: '拆分',
  MERGE: '合并',
  TEXT_ONLY: '仅文字调整',
  CONFLICT: '冲突',
  UNCERTAIN: '无法确定',
  STATIC_SUPPORTED: '静态证据支持',
  INSUFFICIENT: '证据不足',
  POSSIBLE: '可能',
  UNKNOWN: '未知',
  DIRECT: '直接',
  INDIRECT: '间接',
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  UNASSESSED: '未评估',
  KEEP: '保留',
  UPDATE: '修改建议',
  RETIRE: '停用建议',
  ADD_SCENARIO: '新增场景建议',
};
const label = (v: unknown) =>
  Object.hasOwn(labels, optional(v)) ? labels[optional(v)] : optional(v);

export function parseChangeDetail(v: unknown, projectId: number): PageChangeRecord {
  const d = object(v),
    input = object(d.input),
    report = object(d.report);
  if (
    number(d.project_id) !== projectId ||
    !Object.hasOwn(changeModes, string(d.mode)) ||
    !Object.hasOwn(changeStates, string(d.status))
  )
    throw Error('change_response_invalid');
  if (d.origin !== 'AI' && d.origin !== 'IMPORT') throw Error('change_response_invalid');
  if (
    d.status === 'COMPLETED' &&
    (report.analysis_type !== 'CHANGE_IMPACT' ||
      report.contract_version !== 2 ||
      input.analysis_type !== 'CHANGE_IMPACT' ||
      input.contract_version !== 2 ||
      input.project_id !== projectId ||
      typeof input.request_id !== 'string' ||
      !input.request_id ||
      input.mode !== d.mode ||
      report.mode !== d.mode ||
      input.revision !== report.revision ||
      input.request_id !== report.request_id ||
      report.project_id !== projectId)
  )
    throw Error('change_response_invalid');
  if (d.status === 'COMPLETED') {
    for (const group of [
      'changes',
      'function_impacts',
      'code_impacts',
      'case_impacts',
      'risks',
      'historical_reviews',
      'regression_scope',
      'evidence',
      'chains',
      'coverage',
      'limitations',
      'target_results',
    ])
      array(report[group]);
    for (const group of [
      'comparison_pairs',
      'snapshots',
      'context_refs',
      'cases',
      'historical_items',
    ])
      array(input[group]);
  }
  const snapshots = values(input.snapshots),
    evidence = values(report.evidence),
    limitations = values(report.limitations),
    chains = values(report.chains);
  const snapshotMap = new Map(snapshots.map((s) => [string(s.snapshot_ref), s]));
  const evidenceMap = new Map(evidence.map((e) => [string(e.key), e]));
  const limitMap = new Map(
    limitations.map((e) => [
      string(e.key),
      `${string(e.description)}；需补充：${string(e.needed)}`,
    ]),
  );
  function fromEvidence(refs: string[], side: string) {
    return refs
      .flatMap((key) => {
        const e = evidenceMap.get(key);
        if (!e || e.side !== side) return [];
        const s = snapshotMap.get(string(e.snapshot_ref));
        const unit = values(s?.units).find((u) => u.unit_id === e.unit_id);
        return [
          `${optional(s?.name)} · ${optional(unit?.path) || string(e.unit_id)}${e.start_line ? ` L${e.start_line}–${e.end_line}` : ''}\n${optional(e.excerpt) || optional(e.observation)}`,
        ];
      })
      .join('\n\n');
  }
  function item(raw: Record<string, unknown>, group: string): ChangeItem {
    const a = raw.attribution ? object(raw.attribution) : {},
      refs = strings(raw.evidence_refs),
      views = values(raw.target_views);
    const key = string(raw.key);
    return {
      key,
      title:
        optional(raw.title) ||
        optional(raw.subject) ||
        optional(raw.case_ref) ||
        `历史问题 ${optional(raw.history_ref)}`,
      text:
        optional(raw.business_effect) ||
        optional(raw.description) ||
        optional(raw.impact) ||
        optional(raw.reason) ||
        optional(raw.note),
      function: optional(raw.function) || '关联影响',
      kind:
        label(raw.kind) ||
        {
          function_impacts: '功能影响',
          code_impacts: '代码影响',
          case_impacts: '用例建议',
          historical_reviews: '历史复核',
        }[group] ||
        '',
      cause: optional(a.kind),
      severity: label(raw.severity),
      evidence: label(raw.evidence_state),
      before: [optional(raw.before), fromEvidence(refs, 'BEFORE')].filter(Boolean).join('\n\n'),
      after: [optional(raw.after), fromEvidence(refs, 'AFTER'), fromEvidence(refs, 'CONTEXT')]
        .filter(Boolean)
        .join('\n\n'),
      location: refs
        .map((ref) => {
          const e = evidenceMap.get(ref);
          return e ? `${e.side} · ${e.snapshot_ref} / ${e.unit_id} / ${e.segment_id}` : ref;
        })
        .join('；'),
      directness: label(raw.directness),
      certainty: label(raw.certainty),
      attribution: [optional(a.explanation), optional(a.impact_expansion)]
        .filter(Boolean)
        .join('\n'),
      suggestion:
        optional(raw.suggestion) ||
        optional(raw.fix_suggestion) ||
        values(raw.proposed_fields)
          .map((p) => `${p.field}：${p.proposal}`)
          .join('\n'),
      verification:
        optional(raw.verification_suggestion) ||
        views
          .map(
            (view) =>
              `${changeTargets[string(view.target)]}：${view.expected}\n依据：${view.basis}`,
          )
          .join('\n'),
      chain: strings(raw.chain_refs).flatMap((k) => {
        const chain = chains.find((c) => c.key === k);
        return chain
          ? values(chain.edges).map(
              (edge) => `${edge.from} → ${edge.to} · ${label(edge.certainty)}：${edge.note}`,
            )
          : [];
      }),
      missing: [...strings(raw.limitation_refs), ...strings(a.limitation_refs)].map(
        (k) => limitMap.get(k) || k,
      ),
      change_keys: strings(raw.change_refs),
      priority: label(raw.priority),
      caseRef: strings(raw.case_refs).join('、') || optional(raw.case_ref),
      suggested: label(raw.action),
      data: [optional(raw.preconditions), optional(raw.data_requirements)]
        .filter(Boolean)
        .join('\n'),
      action: optional(raw.steps),
      expected: optional(raw.expected),
      details: [
        ...[
          ['trigger', '触发条件'],
          ['actual', '当前静态行为'],
          ['root_cause', '根因'],
          ['severity_reason', '等级依据'],
          ['counterevidence_note', '反证核查'],
          ['result', '历史复核结论'],
        ].flatMap(([field, name]) =>
          raw[field] ? [{ label: name, text: string(raw[field]) }] : [],
        ),
        ...views.flatMap((view) =>
          values(view.comparison_rows).map((row) => ({
            label: `${changeTargets[string(view.target)]} · ${row.label}`,
            text: `${object(row.left).statement}\n→ ${object(row.right).statement}`,
          })),
        ),
        ...strings(raw.questions).map((question) => ({ label: '待确认问题', text: question })),
      ],
    };
  }
  const all = [
    'changes',
    'function_impacts',
    'code_impacts',
    'case_impacts',
    'risks',
    'historical_reviews',
    'regression_scope',
  ].flatMap((group) => values(report[group]).map((x) => string(x.key)));
  if (new Set(all).size !== all.length) throw Error('change_response_invalid');
  const handling = object(d.handling),
    resultHandling: PageChangeRecord['handling'] = Object.create(null);
  for (const [key, value] of Object.entries(handling)) {
    const entry = object(value);
    resultHandling[key] = values(entry.history).map((h) => ({
      status:
        h.status === 'PENDING'
          ? values(report.regression_scope).some((g) => g.key === key)
            ? '待审阅'
            : '待处理'
          : handlingStates[string(h.status)] || string(h.status),
      note: string(h.note),
      time: `${string(h.at)} · ${string(h.actor_name)}`,
    }));
  }
  const selections = object(d.selections || {});
  function version(ref: unknown) {
    const snapshot = snapshotMap.get(string(ref));
    if (!snapshot) throw Error('change_response_invalid');
    const provenance = object(snapshot.provenance);
    const version = string(provenance.version_ref);
    return ['LOCAL', 'LINK'].includes(optional(provenance.source_kind))
      ? snapshotTime(optional(provenance.captured_at)) || version
      : version;
  }
  const pairs = values(input.comparison_pairs).map((p) => ({
    name: string(p.name),
    before: version(p.before_ref),
    after: version(p.after_ref),
    update: p.update_mode === 'INCREMENTAL_SUPPLEMENT' ? '增量补充' : '完整固定版本对比',
    scope: strings(p.scope),
  }));
  return {
    id: String(number(d.id)),
    projectId,
    actorId: d.actor_id === undefined ? undefined : number(d.actor_id),
    title: string(d.title),
    mode: d.mode as ChangeMode,
    createdAt: string(d.created_at),
    updatedAt: string(d.updated_at),
    loaded: true,
    origin: d.origin,
    pairs: pairs.length
      ? pairs
      : values(selections.pairs).map((p) => ({
          name: `来源 #${p.source_id}`,
          before: optional(p.before_ref) || `版本 #${p.before_version_id || '待固定'}`,
          after: optional(p.after_ref) || `版本 #${p.after_version_id || '待固定'}`,
          update: p.update_mode === 'INCREMENTAL_SUPPLEMENT' ? '增量补充' : '固定版本对比',
          scope: strings(p.paths),
        })),
    targets: strings(d.targets).map((t) => changeTargets[t] || t),
    context: [
      ...strings(input.context_refs).map((ref) => {
        const s = snapshotMap.get(ref);
        return s ? `${string(s.name)} @ ${string(object(s.provenance).version_ref)}` : ref;
      }),
      ...values(input.cases).map(
        (c) => `用例 ${c.display_number} · ${c.title} · v${c.design_version}（ID ${c.case_id}）`,
      ),
      ...values(input.historical_items).map(
        (h) =>
          `${h.module === 'CODE_REVIEW' ? '代码' : '需求'}报告 #${h.report_id} / ${h.item_key} · ${h.title}`,
      ),
    ],
    ai: d.ai,
    focus: string(d.focus),
    changes: values(report.changes).map((x) => item(x, 'changes')),
    impacts: [
      'function_impacts',
      'code_impacts',
      'case_impacts',
      'risks',
      'historical_reviews',
    ].flatMap((group) => values(report[group]).map((x) => item(x, group))),
    regressions: values(report.regression_scope).map((x) => item(x, 'regression_scope')),
    handling: resultHandling,
    chatDraft: '',
    inputText: JSON.stringify(input, null, 2),
    reportText: JSON.stringify(report, null, 2),
    status: string(d.status),
    revision: number(d.revision),
    error_code: string(d.error_code),
    can_cancel: d.can_cancel === true,
    terminal_available: d.terminal_available === true,
    can_start: d.can_start === true,
    can_retry: d.can_retry === true,
    retry_preparation: d.retry_preparation === true,
    retry_replan: d.retry_replan === true,
    can_revalidate: d.can_revalidate === true,
    candidate_available: d.candidate_available === true,
    outcome: optional(d.outcome),
    targetResults: values(report.target_results).map((t) => ({
      name: changeTargets[string(t.target)],
      status: string(t.status),
      note: string(t.scope),
    })),
    limitations: [
      ...limitMap.values(),
      ...values(input.historical_items).flatMap((h) =>
        strings(h.review_warnings).map(
          (w) => `历史报告 #${h.report_id} / ${h.item_key} 仍有待核对提示：${w}`,
        ),
      ),
    ],
    summary: report.summary ? string(object(report.summary).conclusion) : '',
    structured: report,
    batches: batches(d.batches),
  };
}
export async function changeDetail(url: string, projectId: number, options?: RequestInit) {
  const result = parseChangeDetail(await apiRequest<unknown>(url, options), projectId);
  const expected = url.match(
    /\/change-analysis\/(\d+)(?:\/(?:handling|cancel|revalidate|start))?(?:\?page_view=true)?$/,
  )?.[1];
  if (expected && result.id !== expected) throw Error('change_response_invalid');
  return result;
}
export async function changeListing(url: string, projectId: number, signal: AbortSignal) {
  const d = object(await apiRequest<unknown>(url, { signal }));
  const items = array(d.items).map((x) => {
    const row = object(x);
    if (number(row.project_id) !== projectId || !Object.hasOwn(changeStates, string(row.status)))
      throw Error('change_response_invalid');
    if (
      !Object.hasOwn(changeModes, string(row.mode)) ||
      (row.origin !== 'AI' && row.origin !== 'IMPORT')
    )
      throw Error('change_response_invalid');
    const summary: PageChangeRecord = {
      id: String(number(row.id)),
      projectId,
      actorId: row.actor_id === undefined ? undefined : number(row.actor_id),
      title: string(row.title),
      status: string(row.status),
      mode: row.mode as ChangeMode,
      origin: row.origin,
      createdAt: string(row.created_at),
      updatedAt: string(row.updated_at),
      revision: number(row.revision),
      targets: strings(row.targets).map((t) => changeTargets[t] || t),
      focus: string(row.focus),
      pairs: [],
      context: [],
      changes: [],
      impacts: [],
      regressions: [],
      handling: {},
      chatDraft: '',
      error_code: string(row.error_code),
      can_cancel: row.can_cancel === true,
      terminal_available: row.terminal_available === true,
      can_start: row.can_start === true,
      can_retry: row.can_retry === true,
      retry_preparation: row.retry_preparation === true,
      retry_replan: row.retry_replan === true,
      batches: batches(row.batches),
    };
    return summary;
  });
  if (typeof d.has_more !== 'boolean') throw Error('change_response_invalid');
  return { items, has_more: d.has_more };
}
