import { useEffect, useId, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { FilePicker } from './FilePicker';
import { GenerationEvidence } from './GenerationEvidence';
import { CASE_COLUMNS, CASE_TYPES, DESIGN_FIELDS, PRIORITIES } from './caseApi';
import type { Design, CaseRow, CaseCategory } from './caseApi';
import { apiRequest } from './api/http';
import { generationAction, generationError } from './generationApi';
import { parseCodeOptions } from './codeAnalysisApi';
import type { CodeOptions } from './codeAnalysisApi';
import { currentHandling, generationDesign, generationKinds } from './generationPage';
import type {
  GenerationDecision,
  GenerationHandling,
  GenerationRecord,
  GenerationSuggestion,
} from './generationPage';

export function GenerationImport({
  projectId,
  onClose,
  onImported,
  onSessionEnd,
}: {
  projectId: number;
  onClose: () => void;
  onImported: (row: GenerationRecord) => void;
  onSessionEnd: () => void;
}) {
  const [input, setInput] = useState(''),
    [report, setReport] = useState(''),
    [title, setTitle] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [confirmed, setConfirmed] = useState(false),
    [options, setOptions] = useState<CodeOptions | null>(null),
    [bindings, setBindings] = useState<
      Record<string, { document_id: number; version_id: number | null }>
    >({});
  const id = useId(),
    controller = useRef<AbortController | null>(null),
    alive = useRef(true),
    pending = useRef(false);
  useEffect(() => {
    alive.current = true;
    const c = new AbortController();
    controller.current = c;
    apiRequest<unknown>(`/api/projects/${projectId}/code-analysis/options`, { signal: c.signal })
      .then(parseCodeOptions)
      .then((o) => {
        if (!c.signal.aborted) setOptions(o);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(generationError(e, onSessionEnd));
      });
    return () => {
      alive.current = false;
      c.abort();
    };
  }, [projectId, onSessionEnd]);
  function materials(value: unknown): {
    snapshot_ref: string;
    name: string;
    kind: string;
    source_id: string;
    version_ref: string;
  }[] {
    if (
      !value ||
      typeof value !== 'object' ||
      !('analysis_type' in value) ||
      !('contract_version' in value) ||
      (value.contract_version !== 2 && value.contract_version !== 3) ||
      !('project_id' in value) ||
      value.project_id !== projectId
    )
      throw Error('generation_contract_invalid');
    if (value.analysis_type === 'CASE_GENERATION_BUNDLE') {
      if (!('batches' in value) || !Array.isArray(value.batches))
        throw Error('generation_contract_invalid');
      const all = value.batches.flatMap((v: unknown) => {
        if (!v || typeof v !== 'object' || !('input' in v))
          throw Error('generation_contract_invalid');
        return materials(v.input);
      });
      return [...new Map(all.map((m) => [m.snapshot_ref, m])).values()];
    }
    if (
      value.analysis_type !== 'CASE_GENERATION' ||
      !('materials' in value) ||
      !Array.isArray(value.materials)
    )
      throw Error('generation_contract_invalid');
    return value.materials.map((v: unknown) => {
      if (
        !v ||
        typeof v !== 'object' ||
        !('snapshot_ref' in v) ||
        typeof v.snapshot_ref !== 'string' ||
        !('name' in v) ||
        typeof v.name !== 'string' ||
        !('kind' in v) ||
        typeof v.kind !== 'string' ||
        !('source_id' in v) ||
        typeof v.source_id !== 'string' ||
        !('version_ref' in v) ||
        typeof v.version_ref !== 'string'
      )
        throw Error('generation_contract_invalid');
      return {
        snapshot_ref: v.snapshot_ref,
        name: v.name,
        kind: v.kind,
        source_id: v.source_id,
        version_ref: v.version_ref,
      };
    });
  }
  let refs: ReturnType<typeof materials> = [],
    problem = '';
  if (input) {
    try {
      refs = materials(JSON.parse(input.replace(/^\uFEFF/, '')));
    } catch {
      problem = '请选择当前项目的用例生成v2/v3输入；v1原型展示文件不能冒充正式报告。';
    }
  }
  async function pick(kind: 'input' | 'report', file: File) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    setConfirmed(false);
    try {
      if (file.size > 16 * 1024 * 1024 || !file.name.toLowerCase().endsWith('.json'))
        throw Error('generation_input_too_large');
      const raw = await file.text();
      JSON.parse(raw.replace(/^\uFEFF/, ''));
      if (!alive.current) return;
      if (kind === 'input') {
        setInput(raw);
        const ms = materials(JSON.parse(raw.replace(/^\uFEFF/, '')));
        setBindings(
          Object.fromEntries(
            ms.map((m) => [
              m.snapshot_ref,
              {
                document_id: /^document-\d+$/.test(m.source_id) ? Number(m.source_id.slice(9)) : 0,
                version_id: /^version-\d+$/.test(m.version_ref)
                  ? Number(m.version_ref.slice(8))
                  : null,
              },
            ]),
          ),
        );
      } else setReport(raw);
      if (!title) setTitle(file.name.replace(/\.json$/i, ''));
    } catch (e) {
      if (alive.current) setError(generationError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title="导入用例生成结果"
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog generation-dialog"
      footer={
        <footer className="change-dialog-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            className="primary"
            type="submit"
            form={id}
            disabled={busy || !input || !report || !!problem}
          >
            确认绑定并保存
          </button>
        </footer>
      }
    >
      <Form
        id={id}
        onSubmit={(e) => {
          e.preventDefault();
          if (
            !confirmed ||
            !title.trim() ||
            refs.some((m) => !bindings[m.snapshot_ref]?.document_id)
          ) {
            setError('请核对每份原件/版本并确认。');
            return;
          }
          if (pending.current) return;
          pending.current = true;
          setBusy(true);
          setError('');
          void generationAction(
            projectId,
            '/import',
            {
              title,
              input_json: input,
              report_json: report,
              bindings: refs.map((m) => ({
                snapshot_ref: m.snapshot_ref,
                ...bindings[m.snapshot_ref],
              })),
            },
            controller.current?.signal,
          )
            .then((row) => {
              if (alive.current) onImported(row);
            })
            .catch((e) => {
              if (alive.current) setError(generationError(e, onSessionEnd));
            })
            .finally(() => {
              pending.current = false;
              if (alive.current) setBusy(false);
            });
        }}
      >
        <p className="notice">配对导入 input.json 与 report.json，导入后仍需审核。</p>
        <div className="form-grid">
          {(['input', 'report'] as const).map((kind) => (
            <section className="evidence" key={kind}>
              <h3>{kind}.json</h3>
              <FilePicker
                accept=".json"
                disabled={busy}
                onChange={(files) => void pick(kind, files[0])}
              />
              <p className="hint">
                {(kind === 'input' ? input : report) ? '已读取文件' : '尚未选择'}
              </p>
            </section>
          ))}
        </div>
        <label className="form-field">
          记录名称
          <input
            required
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        {refs.map((m) => {
          const b = bindings[m.snapshot_ref] || { document_id: 0, version_id: null },
            source = options?.materials.find((s) => s.id === b.document_id);
          return (
            <section className="evidence" key={m.snapshot_ref}>
              <strong>
                {m.name} · {m.version_ref}
              </strong>
              <FormSelect
                label="关联项目原件"
                value={String(b.document_id || '')}
                options={[
                  { value: '', label: '请选择已有原件' },
                  ...(options?.materials
                    .filter((s) => s.purpose === m.kind)
                    .map((s) => ({ value: String(s.id), label: s.name })) || []),
                ]}
                onChange={(v) => {
                  setConfirmed(false);
                  setBindings((old) => ({
                    ...old,
                    [m.snapshot_ref]: { document_id: Number(v), version_id: null },
                  }));
                }}
              />
              {source && ['FILE', 'DIRECTORY'].includes(source.kind) && (
                <FormSelect
                  label="固定原件版本"
                  value={String(b.version_id || '')}
                  options={[
                    { value: '', label: '请选择固定版本' },
                    ...source.versions.map((v) => ({
                      value: String(v.id),
                      label: `v${v.number} · ${v.filename}`,
                    })),
                  ]}
                  onChange={(v) => {
                    setConfirmed(false);
                    setBindings((old) => ({
                      ...old,
                      [m.snapshot_ref]: { ...b, version_id: v ? Number(v) : null },
                    }));
                  }}
                />
              )}
              {source && !['FILE', 'DIRECTORY'].includes(source.kind) && (
                <p className="hint">仓库或链接须匹配项目已保存的正文快照。</p>
              )}
            </section>
          );
        })}
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          已核对原件、固定版本及内部用例引用；内部ID不授予写权限
        </label>
        {(error || problem) && (
          <p className="form-error" role="alert">
            {error || problem}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
export function GenerationDetail({
  record,
  suggestion,
  actor,
  currentCase,
  categories = [],
  busy = false,
  applicationStatus,
  reviewMode = false,
  refreshKey = 0,
  confirmationOpen = false,
  serverError = '',
  onClose,
  onSave,
  onAsk,
  onNext,
  onPrevious,
  position,
}: {
  record: GenerationRecord;
  suggestion: GenerationSuggestion;
  actor: string;
  currentCase?: CaseRow;
  categories?: CaseCategory[];
  busy?: boolean;
  applicationStatus?: string;
  reviewMode?: boolean;
  refreshKey?: number;
  confirmationOpen?: boolean;
  serverError?: string;
  onClose: () => void;
  onSave: (
    h: GenerationHandling,
    revision: number,
    intent: 'save' | 'previous' | 'next' | 'review',
  ) => void;
  onAsk: () => void;
  onNext?: () => void;
  onPrevious?: () => void;
  position?: { index: number; total: number };
}) {
  const h = currentHandling(record, suggestion),
    [draft, setDraft] = useState<Design>(structuredClone(h?.draft || suggestion.design)),
    [note, setNote] = useState(h?.note || ''),
    [checked, setChecked] = useState(h?.evidenceChecked || false),
    [ignore, setIgnore] = useState(h?.status === '已忽略'),
    [targetChecked, setTargetChecked] = useState(false),
    [categoryId, setCategoryId] = useState(String(h?.categoryId ?? currentCase?.category_id ?? 0)),
    [editedFields, setEditedFields] = useState<(keyof Design)[]>(h?.editedFields || []),
    [error, setError] = useState(''),
    [revision, setRevision] = useState(h?.revision || 0);
  const id = useId(),
    refreshed = useRef(refreshKey),
    hadConfirmation = useRef(confirmationOpen);
  useEffect(() => {
    // Only acknowledge explicit saves; polling must preserve an unsaved draft.
    if (refreshed.current === refreshKey) return;
    refreshed.current = refreshKey;
    setDraft(structuredClone(h?.draft || suggestion.design));
    setNote(h?.note || '');
    setChecked(h?.evidenceChecked || false);
    setIgnore(h?.status === '已忽略');
    setTargetChecked(false);
    setCategoryId(String(h?.categoryId ?? currentCase?.category_id ?? 0));
    setEditedFields(h?.editedFields || []);
    setRevision(h?.revision || 0);
    setError('');
  }, [refreshKey, h, suggestion.design, currentCase?.category_id]);
  useEffect(() => {
    if (hadConfirmation.current && !confirmationOpen) {
      const dialog = document.getElementById(id)?.closest('dialog');
      const target =
        dialog?.querySelector<HTMLButtonElement>('button[value="review"]:not(:disabled)') ||
        dialog?.querySelector<HTMLButtonElement>('button[aria-label="关闭对话框"]');
      target?.focus({ preventScroll: true });
    }
    hadConfirmation.current = confirmationOpen;
  }, [confirmationOpen, id]);
  const applied = h?.status === '已应用' || h?.status === '已复用';
  const applying = applicationStatus === 'QUEUED' || applicationStatus === 'RUNNING',
    editingDisabled = busy || applying || applied;
  const noteRequired = ignore || suggestion.blocked || h?.status === '需人工确认';
  const fieldIssue = (field: keyof Design) => {
    if (editingDisabled || ignore) return '';
    if (
      ['NEW', 'UPDATE'].includes(suggestion.kind) &&
      ['title', 'steps', 'expected'].includes(field) &&
      !draft[field].trim()
    )
      return '此项不能为空，请补充后再确认。';
    const baseline = h?.reviewedTarget?.design || suggestion.before;
    if (
      h?.status === '需人工确认' &&
      currentCase &&
      baseline &&
      !targetChecked &&
      currentCase[field] !== baseline[field]
    )
      return '当前库此项内容已变化，请对照当前版本后确认本次修订。';
    return '';
  };
  const dirty =
    JSON.stringify([draft, note, checked, ignore, categoryId, editedFields, targetChecked]) !==
    JSON.stringify([
      h?.draft || suggestion.design,
      h?.note || '',
      h?.evidenceChecked || false,
      h?.status === '已忽略',
      String(h?.categoryId ?? currentCase?.category_id ?? 0),
      h?.editedFields || [],
      false,
    ]);
  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (editingDisabled) return;
    const submitted = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const intent =
      submitted?.value === 'review'
        ? 'review'
        : submitted?.value === 'previous'
          ? 'previous'
          : submitted?.value === 'next'
            ? 'next'
            : 'save';
    if (intent === 'review' && ignore) {
      setError('当前建议选择了忽略，不能审核入库。');
      return;
    }
    if (noteRequired && !note.trim()) {
      setError('忽略、解决冲突或处理失败项需要填写说明。');
      return;
    }
    if (reviewMode && !ignore && !checked) {
      setError('请核对固定依据与可执行预期。');
      return;
    }
    if (!ignore && currentCase && h?.status === '需人工确认' && !targetChecked) {
      setError('请对照当前用例版本并确认，才能准备再次预览。');
      return;
    }
    try {
      const d = generationDesign(draft);
      if (
        !ignore &&
        ['NEW', 'UPDATE'].includes(suggestion.kind) &&
        !['title', 'steps', 'expected'].every((f) => d[f as keyof Design].trim())
      )
        throw Error('验证子项、步骤及预期不能为空。');
      onSave(
        {
          draft: d,
          editedFields,
          categoryId: categoryId ? Number(categoryId) : undefined,
          note: note.trim(),
          status: ignore ? '已忽略' : '待审阅',
          actor,
          time: new Date().toISOString(),
          revision: revision + 1,
          evidenceChecked: !reviewMode && intent === 'review' ? true : checked,
          resolved: (!reviewMode && intent === 'review' ? true : checked) && !ignore,
          reviewedTarget:
            !ignore && targetChecked && currentCase
              ? {
                  id: currentCase.id,
                  version: currentCase.version,
                  design: generationDesign(
                    Object.fromEntries(DESIGN_FIELDS.map((f) => [f, currentCase[f]])),
                  ),
                }
              : h?.reviewedTarget,
        },
        revision,
        intent,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '草稿无法保存。');
    }
  }
  const label = (field: keyof Design) =>
    CASE_COLUMNS.find((c) => c[0] === field)?.[1] ||
    (
      { data_requirements: '测试数据要求', cleanup: '清理要求' } as Partial<
        Record<keyof Design, string>
      >
    )[field] ||
    field;
  return (
    <CaseDialog
      title={`建议详情 · ${generationKinds[suggestion.kind]} / ${suggestion.key}`}
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog generation-dialog generation-detail-dialog"
      sideControls={
        <nav className="generation-detail-switcher" aria-label="切换用例">
          {(
            [
              ['previous', onPrevious, '上一条'],
              ['next', onNext, '下一条'],
            ] as const
          ).map(([direction, navigate, label]) => (
            <button
              key={direction}
              className={`generation-detail-nav ${direction}`}
              type={dirty && !applied && !applying ? 'submit' : 'button'}
              form={dirty && !applied && !applying ? id : undefined}
              name="intent"
              value={direction}
              disabled={busy || !navigate}
              onClick={dirty && !applied && !applying ? undefined : navigate}
              title={dirty && !applied && !applying ? `先保存当前修改，再切换${label}` : label}
              aria-label={dirty && !applied && !applying ? `保存并${label}` : label}
            >
              <svg
                aria-hidden="true"
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d={direction === 'previous' ? 'm14 6-6 6 6 6' : 'm10 6 6 6-6 6'} />
              </svg>
            </button>
          ))}
        </nav>
      }
      footer={
        <footer className="change-dialog-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            {reviewMode ? '返回批量审核' : '关闭'}
          </button>
          {!reviewMode && (
            <button type="button" disabled={busy} onClick={onAsk}>
              引用提问
            </button>
          )}
          {!applied && (
            <button type="submit" form={id} name="intent" value="save" disabled={editingDisabled}>
              保存人工草稿
            </button>
          )}
          {!applied && !reviewMode && (
            <button
              type="submit"
              form={id}
              name="intent"
              value="review"
              className="primary"
              disabled={editingDisabled || ignore}
            >
              审核确认入库
            </button>
          )}
        </footer>
      }
    >
      {position && (
        <p className="hint">
          当前筛选第{position.index + 1}/{position.total}条，包含其他分页。
          {!onPrevious ? '已到第一条。' : ''}
          {!onNext ? '已到最后一条。' : ''}
        </p>
      )}
      {applied && <p className="notice">本条已应用或复用，仅供查看；继续审阅下一条。</p>}
      {applying && (
        <p className="notice" role="status">
          {applicationStatus === 'QUEUED' ? '已提交审核，等待入库。' : '正在审核入库。'}{' '}
          完成前请勿重复提交，可关闭后查看结果。
        </p>
      )}
      <p className="notice">审核入库后，新增或修改项为“已审核、未测”；复用保留原测试记录。</p>
      {suggestion.caseId && (
        <p className="hint mono">
          内部用例ID {suggestion.caseId} · 固定设计v{suggestion.baseVersion}
        </p>
      )}
      {suggestion.before && (
        <div className="generation-three-way">
          {[
            ['可取得历史设计', suggestion.generated],
            [
              currentCase ? `当前库人工版本 v${currentCase.version}` : '输入固定人工版本',
              currentCase || suggestion.before,
            ],
            ['本次建议', suggestion.design],
          ].map(([t, d]) => (
            <section className="evidence" key={String(t)}>
              <strong>{String(t)}</strong>
              <p>{typeof d === 'object' && d ? d.expected : '无历史基准，不补造'}</p>
            </section>
          ))}
        </div>
      )}
      {record.failures
        .filter((f) => f.key === suggestion.key)
        .map((f, i) => (
          <p className="notice warn" key={i}>
            应用需人工核对：{f.reason} · {f.time}
            {f.categoryMode &&
              ` · 本次分类：${f.categoryMode === 'CLEAR' ? '未分类' : f.categoryMode === 'SET' ? categories.find((c) => c.id === f.categoryId)?.name || `分类ID ${f.categoryId}（需核对）` : '保持原分类'}`}
          </p>
        ))}
      {suggestion.before && (
        <div className="table-wrap generation-differences">
          <table>
            <thead>
              <tr>
                <th>字段</th>
                <th>当前固定值</th>
                <th>建议值</th>
              </tr>
            </thead>
            <tbody>
              {DESIGN_FIELDS.filter((f) => suggestion.before?.[f] !== draft[f]).map((f) => (
                <tr key={f}>
                  <td>{label(f)}</td>
                  <td>{suggestion.before?.[f]}</td>
                  <td>{draft[f]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Form id={id} onSubmit={submit}>
        {serverError && (
          <p className="form-error" role="alert">
            {serverError}
          </p>
        )}
        {['NEW', 'UPDATE'].includes(suggestion.kind) && (
          <FormSelect
            label="用例分类"
            disabled={editingDisabled}
            value={categoryId}
            options={[
              { value: '0', label: '未分类' },
              ...categories.map((c) => ({ value: String(c.id), label: c.name })),
            ]}
            onChange={setCategoryId}
          />
        )}
        <div className="form-grid">
          {DESIGN_FIELDS.map((f) =>
            f === 'priority' ? (
              <FormSelect
                disabled={editingDisabled || ['RETIRE', 'REUSE'].includes(suggestion.kind)}
                key={f}
                label="优先级"
                value={draft[f]}
                options={PRIORITIES.map((v) => ({ value: v, label: v || '未指定' }))}
                onChange={(v) => {
                  setDraft((d) => ({ ...d, [f]: v }));
                  setEditedFields((old) => [...new Set([...old, f])]);
                  setChecked(false);
                }}
              />
            ) : f === 'case_type' ? (
              <FormSelect
                disabled={editingDisabled || ['RETIRE', 'REUSE'].includes(suggestion.kind)}
                key={f}
                label="用例类型"
                value={draft[f]}
                editable
                maxLength={200}
                options={CASE_TYPES.map((v) => ({ value: v, label: v || '未指定' }))}
                onChange={(v) => {
                  setDraft((d) => ({ ...d, [f]: v }));
                  setEditedFields((old) => [...new Set([...old, f])]);
                  setChecked(false);
                }}
              />
            ) : (
              <label
                key={f}
                className={`form-field ${['preconditions', 'steps', 'expected', 'remark'].includes(f) ? 'span2' : ''}`}
              >
                {label(f)}
                <textarea
                  aria-label={label(f)}
                  aria-invalid={!!fieldIssue(f)}
                  aria-describedby={fieldIssue(f) ? `${id}-${f}-issue` : undefined}
                  disabled={editingDisabled}
                  required={
                    !ignore &&
                    ['NEW', 'UPDATE'].includes(suggestion.kind) &&
                    ['title', 'steps', 'expected'].includes(f)
                  }
                  maxLength={
                    ['steps', 'expected', 'preconditions'].includes(f)
                      ? 30000
                      : ['remark', 'data_requirements', 'cleanup'].includes(f)
                        ? 10000
                        : f === 'module'
                          ? 500
                          : f === 'structure'
                            ? 1000
                            : 4000
                  }
                  readOnly={applied || ['RETIRE', 'REUSE'].includes(suggestion.kind)}
                  value={draft[f]}
                  onChange={(e) => {
                    setDraft((d) => ({ ...d, [f]: e.target.value }));
                    setEditedFields((old) => [...new Set([...old, f])]);
                    setChecked(false);
                  }}
                />
                {fieldIssue(f) && (
                  <span className="form-error generation-field-error" id={`${id}-${f}-issue`}>
                    {fieldIssue(f)}
                  </span>
                )}
              </label>
            ),
          )}
        </div>
        <label className="form-field">
          人工处理说明
          <textarea
            aria-label="人工处理说明"
            required={!!noteRequired}
            aria-invalid={!editingDisabled && !!noteRequired && !note.trim()}
            aria-describedby={
              !editingDisabled && noteRequired && !note.trim() ? `${id}-note-issue` : undefined
            }
            disabled={editingDisabled}
            maxLength={2000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {!editingDisabled && noteRequired && !note.trim() && (
            <span className="form-error generation-field-error" id={`${id}-note-issue`}>
              本条需要人工处理，请填写核对结论或处理说明。
            </span>
          )}
        </label>
        {reviewMode && (
          <label className="check-label">
            <input
              disabled={editingDisabled}
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
            />
            已核对固定依据、预期和人工内容
            {suggestion.blocked ? '，已核对待确认事项；执行准备待补项仍保留' : ''}
          </label>
        )}
        {currentCase && h?.status === '需人工确认' && (
          <label className="check-label">
            <input
              disabled={editingDisabled}
              type="checkbox"
              checked={targetChecked}
              onChange={(e) => setTargetChecked(e.target.checked)}
            />
            已对照当前库v{currentCase.version}，本次修订仅用于再次预览
          </label>
        )}
        <label className="check-label">
          <input
            disabled={editingDisabled}
            type="checkbox"
            checked={ignore}
            onChange={(e) => setIgnore(e.target.checked)}
          />
          忽略本建议（保存审计）
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Form>
      <h3 className="mt">固定需求证据</h3>
      <GenerationEvidence record={record} suggestion={suggestion} />
      <details className="mt">
        <summary>人工处理历史 · {record.handling[suggestion.key]?.length || 0}次</summary>
        {record.handling[suggestion.key]?.map((h, i) => (
          <p key={i} className="hint">
            {h.actor} · {new Date(h.time).toLocaleString()} · {h.status} · {h.note}
          </p>
        ))}
      </details>
    </CaseDialog>
  );
}
export function GenerationClarification({
  record,
  questionKey,
  actor,
  onClose,
  onSave,
  busy = false,
  serverError = '',
}: {
  record: GenerationRecord;
  questionKey: string;
  actor: string;
  onClose: () => void;
  onSave: (value: GenerationDecision, expected: number) => void;
  busy?: boolean;
  serverError?: string;
}) {
  const q = record.questions.find((q) => q.key === questionKey)!,
    old = record.decisions.filter((d) => d.questionKey === q.key).at(-1),
    [conclusion, setConclusion] = useState(old?.conclusion || ''),
    [basis, setBasis] = useState(old?.basis || q.evidence),
    [affected, setAffected] = useState(old?.affected || q.function),
    [confirmed, setConfirmed] = useState(false),
    [error, setError] = useState(''),
    id = useId(),
    openedVersion = useRef(old?.version || 0);
  return (
    <CaseDialog
      title="确认业务澄清结论"
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog generation-dialog"
      footer={
        <footer className="change-dialog-footer">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button type="submit" form={id} className="primary">
            确认业务结论
          </button>
        </footer>
      }
    >
      <p className="notice">确认结论后可补生成受影响场景。</p>
      {serverError && (
        <p className="form-error" role="alert">
          {serverError}
        </p>
      )}
      <section className="evidence">
        <strong>{q.title}</strong>
        <p>{q.text}</p>
        <p>{q.evidence}</p>
      </section>
      <Form
        id={id}
        onSubmit={(e) => {
          e.preventDefault();
          if (!confirmed || ![conclusion, basis, affected].every((s) => s.trim())) {
            setError('请填写结论、依据和受影响范围，并明确确认。');
            return;
          }
          onSave(
            {
              key: `${q.key}-D${openedVersion.current + 1}`,
              questionKey: q.key,
              function: q.function,
              conclusion: conclusion.trim(),
              basis: basis.trim(),
              affected: affected.trim(),
              actor,
              time: new Date().toISOString(),
              version: openedVersion.current + 1,
            },
            openedVersion.current,
          );
        }}
      >
        <label className="form-field">
          业务结论
          <textarea
            disabled={busy}
            required
            maxLength={4000}
            value={conclusion}
            onChange={(e) => {
              setConclusion(e.target.value);
              setConfirmed(false);
            }}
          />
        </label>
        <label className="form-field">
          依据与资料版本
          <textarea
            disabled={busy}
            required
            maxLength={2000}
            value={basis}
            onChange={(e) => {
              setBasis(e.target.value);
              setConfirmed(false);
            }}
          />
        </label>
        <label className="form-field">
          受影响功能/场景范围
          <input
            disabled={busy}
            required
            maxLength={500}
            value={affected}
            onChange={(e) => {
              setAffected(e.target.value);
              setConfirmed(false);
            }}
          />
        </label>
        <label className="check-label">
          <input
            disabled={busy}
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          确认该结论可作为此范围后续生成依据
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Form>
    </CaseDialog>
  );
}
