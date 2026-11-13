import { PageJump } from './PageJump';
import { useEffect, useRef, useState } from 'react';
import { CaseDialog } from './CaseDialog';
import { FormSelect } from './FormSelect';
import { GenerationDetail } from './CaseGenerationDialogs';
import { GenerationEvidence } from './GenerationEvidence';
import { CASE_COLUMNS, DESIGN_FIELDS } from './caseApi';
import type { CaseCategory, Design } from './caseApi';
import { currentHandling, generationKinds } from './generationPage';
import type { GenerationHandling, GenerationPreviewItem, GenerationRecord } from './generationPage';

type Decision = {
  action: 'apply' | 'reuse' | 'restore' | 'include' | 'ignore';
  targetId: number | null;
  reason: string;
};
type Category = { mode: 'KEEP' | 'SET' | 'CLEAR'; id: number | null };
export type ReviewItem = {
  key: string;
  draft_revision: number;
  action: Decision['action'];
  target_id: number | null;
  target_version: number | null;
  reason: string;
  category_mode: Category['mode'];
  category_id: number | null;
};
const keep: Category = { mode: 'KEEP', id: null };
export function defaultDecision(i: GenerationPreviewItem): Decision {
  return {
    action: i.matches.length ? 'reuse' : 'apply',
    targetId: i.matches.length === 1 ? i.matches[0].id : null,
    reason: '',
  };
}
export function reviewProblem(i: GenerationPreviewItem, d = defaultDecision(i)) {
  if (i.problem) return i.problem;
  if (['include', 'ignore', 'restore'].includes(d.action) && !d.reason.trim())
    return '请填写处理原因。';
  if (i.matches.length && ['reuse', 'restore'].includes(d.action)) {
    const target = i.matches.find((c) => c.id === d.targetId);
    if (!target) return '请选择要复用的用例。';
    if (target.lifecycle === 'RETIRED' && d.action !== 'restore')
      return '该用例已停用，请明确恢复后再复用。';
    if (target.lifecycle !== 'RETIRED' && d.action === 'restore')
      return '该用例未停用，请选择复用。';
  }
  return '';
}
function canClassify(i: GenerationPreviewItem, d: Decision) {
  return ['NEW', 'UPDATE'].includes(i.kind) && ['apply', 'include'].includes(d.action);
}
function categoryChoice(value: string): Category {
  return value === 'CLEAR' ? { mode: 'CLEAR', id: null } : { mode: 'SET', id: Number(value) };
}
export function GenerationSingleReview({
  items,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  items: GenerationPreviewItem[];
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (items: ReviewItem[]) => void;
}) {
  const submitted = useRef(false);
  useEffect(() => {
    submitted.current = false;
  }, [busy, error, items]);
  const item = items[0],
    problem = items.length === 1 ? reviewProblem(item) : '单条范围已变化，请重新打开。',
    decision = item ? defaultDecision(item) : null,
    target = item?.matches.find((c) => c.id === decision?.targetId) || item?.target;
  return (
    <CaseDialog
      title="确认入库"
      busy={busy}
      onClose={onClose}
      className="generation-single-confirm"
      footer={
        <footer className="change-dialog-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="primary"
            disabled={busy || !!problem}
            onClick={() => {
              if (busy || problem || submitted.current || !item || !decision) return;
              submitted.current = true;
              onSubmit([
                {
                  key: item.key,
                  draft_revision: item.revision,
                  action: decision.action,
                  target_id: decision.targetId || item.target?.id || null,
                  target_version: target?.version || null,
                  reason: '',
                  category_mode: 'KEEP',
                  category_id: null,
                },
              ]);
            }}
          >
            {busy ? '正在入库…' : '确认'}
          </button>
        </footer>
      }
    >
      <p>确认将本条用例审核入库？</p>
      {!!item?.matches.length && !problem && (
        <p className="hint">已存在相同用例，将关联复用并追加本次审核，保留原设计和测试记录。</p>
      )}
      {problem && (
        <p className="form-error" role="alert">
          {problem}请先返回表格或详情处理。
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </CaseDialog>
  );
}
export function GenerationReview({
  record,
  items,
  categories,
  actor,
  busy,
  error,
  onClose,
  onSubmit,
  onSave,
}: {
  record: GenerationRecord;
  items: GenerationPreviewItem[];
  categories: CaseCategory[];
  actor: string;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (items: ReviewItem[]) => void;
  onSave: (key: string, h: GenerationHandling, revision: number) => Promise<boolean>;
}) {
  const [selected, setSelected] = useState(
      () => new Set(items.filter((i) => !reviewProblem(i)).map((i) => i.key)),
    ),
    [current, setCurrent] = useState(items[0]?.key || ''),
    [page, setPage] = useState(1),
    [settings, setSettings] = useState<Record<string, Category>>({}),
    [decisions, setDecisions] = useState<Record<string, Decision>>({}),
    [batchCategory, setBatchCategory] = useState(''),
    [confirmed, setConfirmed] = useState(false),
    [notice, setNotice] = useState(''),
    [editing, setEditing] = useState(''),
    [openedDuplicates, setOpenedDuplicates] = useState<Record<string, boolean>>({});
  const submitted = useRef(false);
  useEffect(() => {
    setConfirmed(false);
  }, [items, record.serverRevision, categories]);
  useEffect(() => {
    if (!busy) submitted.current = false;
  }, [busy]);
  const decision = (i: GenerationPreviewItem) =>
      i.matches.length ? decisions[i.key] || defaultDecision(i) : defaultDecision(i),
    problem = (i: GenerationPreviewItem) => {
      const s = settings[i.key];
      return (
        reviewProblem(i, decision(i)) ||
        (canClassify(i, decision(i)) && s?.mode === 'SET' && !categories.some((c) => c.id === s.id)
          ? '所选分类已失效，请重新选择。'
          : '')
      );
    },
    chosen = items.filter((i) => selected.has(i.key) && !problem(i)),
    ignored = chosen.filter((i) => decision(i).action === 'ignore').length,
    incoming = chosen.length - ignored,
    available = items.filter((i) => !problem(i) && i.kind !== 'RETIRE'),
    allSelected = available.length > 0 && available.every((i) => selected.has(i.key)),
    classified = chosen.filter((i) => canClassify(i, decision(i))),
    active = items.find((i) => i.key === current) || items[0],
    pages = Math.max(1, Math.ceil(items.length / 10)),
    shownPage = Math.min(page, pages),
    categoryName = (id: number | null | undefined) =>
      categories.find((c) => c.id === id)?.name || (id ? `分类ID ${id}（需核对）` : '未分类');
  function originalCategory(i: GenerationPreviewItem) {
    const suggestion = record.suggestions.find((s) => s.key === i.key);
    return (
      i.categoryId ??
      (suggestion ? currentHandling(record, suggestion)?.categoryId : undefined) ??
      i.target?.category_id ??
      null
    );
  }
  function target(i: GenerationPreviewItem) {
    return i.matches.find((c) => c.id === decision(i).targetId) || i.target;
  }
  function finalCategory(i: GenerationPreviewItem) {
    if (!canClassify(i, decision(i))) return target(i)?.category_id;
    const s = settings[i.key] || keep;
    return s.mode === 'SET' ? s.id : s.mode === 'CLEAR' ? null : originalCategory(i);
  }
  function changeDecision(i: GenerationPreviewItem, patch: Partial<Decision>) {
    const next = { ...decision(i), ...patch };
    setDecisions((old) => ({ ...old, [i.key]: next }));
    setConfirmed(false);
    if (reviewProblem(i, next)) setSelected((old) => new Set([...old].filter((k) => k !== i.key)));
  }
  function submit() {
    if (busy || submitted.current || !confirmed || !chosen.length) return;
    submitted.current = true;
    onSubmit(
      chosen.map((i) => {
        const d = decision(i),
          t = target(i),
          c = canClassify(i, d) ? settings[i.key] || keep : keep;
        return {
          key: i.key,
          draft_revision: i.revision,
          action: d.action,
          target_id: d.targetId || i.target?.id || null,
          target_version: t?.version || null,
          reason: d.reason,
          category_mode: c.mode,
          category_id: c.id,
        };
      }),
    );
  }
  const editItem = items.find((i) => i.key === editing),
    suggestion = record.suggestions.find((s) => s.key === editing);
  if (editItem && suggestion)
    return (
      <GenerationDetail
        key={`${editing}:${editItem.revision}`}
        record={record}
        suggestion={suggestion}
        actor={actor}
        currentCase={editItem.target}
        categories={categories}
        busy={busy}
        serverError={error}
        reviewMode
        onClose={() => setEditing('')}
        onAsk={() => setEditing('')}
        onSave={(h, revision) => {
          void onSave(editing, h, revision).then((saved) => {
            if (saved) {
              setEditing('');
              setConfirmed(false);
              setNotice('内容已更新，其他用例的选择和分类保留。');
            }
          });
        }}
      />
    );
  if (!active) return null;
  const d = decision(active),
    t = target(active),
    reuse = active.kind === 'REUSE' || ['reuse', 'restore'].includes(d.action),
    design = reuse && t ? t : active.design,
    fieldLabel = (f: keyof Design) =>
      CASE_COLUMNS.find((c) => c[0] === f)?.[1] ||
      (
        { data_requirements: '测试数据要求', cleanup: '清理要求' } as Partial<
          Record<keyof Design, string>
        >
      )[f] ||
      f,
    renderField = (f: keyof Design) => (
      <section className="generation-review-value" key={f}>
        <h4>{fieldLabel(f)}</h4>
        <div>{design[f] || '未填写'}</div>
      </section>
    ),
    mainFields: (keyof Design)[] = ['preconditions', 'steps', 'expected'],
    activeSetting = settings[active.key] || keep;
  return (
    <CaseDialog
      title="批量审核用例"
      busy={busy}
      onClose={onClose}
      wide
      className="generation-review-dialog"
      footer={
        <footer className="change-dialog-footer generation-review-footer">
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            我已审核这 {chosen.length} 条用例
          </label>
          <div className="between">
            <span className="hint">复用保留原分类；确认后直接逐条入库并返回结果。</span>
            <div className="row">
              <button disabled={busy} onClick={onClose}>
                取消
              </button>
              <button
                className="primary"
                disabled={busy || !confirmed || !chosen.length}
                onClick={submit}
              >
                {busy
                  ? '正在入库…'
                  : incoming
                    ? `确认入库（${incoming}条）`
                    : `确认忽略（${ignored}条）`}
              </button>
            </div>
          </div>
        </footer>
      }
    >
      <div className="generation-review-head">
        <div>
          <strong>
            已勾选 {chosen.length} / {items.length} 条
          </strong>
          {!!ignored && <span className="hint"> · 其中{ignored}条忽略</span>}
          {items.some((i) => problem(i)) && (
            <span className="generation-failure">
              {' '}
              · {items.filter((i) => problem(i)).length}条需处理，暂不入库
            </span>
          )}
          <p className="hint">点左侧用例查看内容，不想入库的取消勾选。</p>
        </div>
        <div>
          <FormSelect
            label="统一分类"
            value={batchCategory}
            disabled={busy || !classified.length}
            options={[
              { value: '', label: '选择分类…', disabled: true },
              { value: 'CLEAR', label: '未分类' },
              ...categories.map((c) => ({ value: String(c.id), label: c.name })),
            ]}
            onChange={(value) => {
              if (!value) return;
              const setting = categoryChoice(value);
              setSettings((old) => ({
                ...old,
                ...Object.fromEntries(classified.map((i) => [i.key, setting])),
              }));
              setBatchCategory(value);
              setConfirmed(false);
              setNotice(`已更新${classified.length}条分类，确认入库后生效。`);
            }}
          />
          <p className="hint">选好立即应用到已勾选的{classified.length}条新增 / 修改用例。</p>
        </div>
      </div>
      {notice && (
        <p className="hint" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="generation-review-grid">
        <aside className="generation-review-list">
          <label className="check-label generation-review-all">
            <input
              type="checkbox"
              checked={allSelected}
              disabled={busy || !available.length}
              onChange={(e) => {
                setSelected(
                  e.target.checked
                    ? new Set([...selected, ...available.map((i) => i.key)])
                    : new Set(),
                );
                setConfirmed(false);
                setBatchCategory('');
              }}
            />
            全选可入库用例（跨页）
          </label>
          <div className="generation-review-list-scroll">
            {items.slice((shownPage - 1) * 10, shownPage * 10).map((i) => (
              <div
                className={`generation-review-row${i.key === active.key ? ' active' : ''}`}
                key={i.key}
              >
                <input
                  type="checkbox"
                  aria-label={`入库 ${i.key}`}
                  checked={selected.has(i.key) && !problem(i)}
                  disabled={busy || !!problem(i)}
                  onChange={(e) => {
                    setSelected((old) => {
                      const next = new Set(old);
                      if (e.target.checked) next.add(i.key);
                      else next.delete(i.key);
                      return next;
                    });
                    setConfirmed(false);
                    setBatchCategory('');
                  }}
                />
                <button
                  aria-current={i.key === active.key ? 'true' : undefined}
                  disabled={busy}
                  onClick={() => setCurrent(i.key)}
                >
                  <strong>{i.design.title}</strong>
                  <small>
                    {i.key} · {generationKinds[i.kind]} · {categoryName(finalCategory(i))}
                  </small>
                  {problem(i) && <small className="generation-failure">需处理：{problem(i)}</small>}
                </button>
              </div>
            ))}
          </div>
          <nav className="generation-review-pagination" aria-label="批量审核分页">
            <span>
              第 {shownPage} / {pages} 页
            </span>
            <div className="row">
              <button disabled={busy || shownPage === 1} onClick={() => setPage(shownPage - 1)}>
                上一页
              </button>
              <button disabled={busy || shownPage === pages} onClick={() => setPage(shownPage + 1)}>
                下一页
              </button>
              <PageJump page={shownPage} onChange={setPage} pages={pages} disabled={busy} />
            </div>
          </nav>
        </aside>
        <article className="generation-review-content">
          <div className="between">
            <span className="badge">{generationKinds[active.kind]}</span>
            <button className="small" disabled={busy} onClick={() => setEditing(active.key)}>
              修改内容
            </button>
          </div>
          <h3>{design.title}</h3>
          {problem(active) && (
            <p className="generation-failure">{problem(active)} 本条暂不入库。</p>
          )}
          {canClassify(active, d) ? (
            <FormSelect
              label="这条用例的分类"
              value={
                activeSetting.mode === 'SET'
                  ? String(activeSetting.id)
                  : activeSetting.mode === 'CLEAR'
                    ? 'CLEAR'
                    : String(originalCategory(active) || 'CLEAR')
              }
              disabled={busy}
              options={[
                { value: 'CLEAR', label: '未分类' },
                ...categories.map((c) => ({ value: String(c.id), label: c.name })),
              ]}
              onChange={(value) => {
                setSettings((old) => ({ ...old, [active.key]: categoryChoice(value) }));
                setBatchCategory('');
                setConfirmed(false);
              }}
            />
          ) : (
            <p className="hint">
              {reuse
                ? `复用已有用例，保留分类：${categoryName(finalCategory(active))}`
                : '本条不修改分类。'}
            </p>
          )}
          {t && (
            <p className="hint">
              已有用例 {t.number} / v{t.version}
            </p>
          )}
          {mainFields.map(renderField)}
          <details className="evidence">
            <summary>其他用例信息</summary>
            {DESIGN_FIELDS.filter((f) => f !== 'title' && !mainFields.includes(f)).map(renderField)}
          </details>
          {active.kind === 'UPDATE' && active.target && (
            <details className="evidence">
              <summary>查看修改内容</summary>
              {DESIGN_FIELDS.filter((f) => active.target![f] !== active.design[f]).map((f) => (
                <div className="generation-review-value" key={f}>
                  <h4>{fieldLabel(f)}</h4>
                  <div>原内容：{active.target![f] || '空'}</div>
                  <div>新内容：{active.design[f] || '空'}</div>
                </div>
              ))}
            </details>
          )}
          {!!active.matches.length && (
            <details
              className="evidence"
              key={active.key}
              open={!!problem(active) || !!openedDuplicates[active.key]}
              onToggle={(e) => {
                const open = e.currentTarget.open;
                setOpenedDuplicates((old) =>
                  old[active.key] === open ? old : { ...old, [active.key]: open },
                );
              }}
            >
              <summary>
                已有相同用例 ·{' '}
                {d.action === 'include'
                  ? '仍然新增'
                  : d.action === 'ignore'
                    ? '忽略本条'
                    : d.action === 'restore'
                      ? '恢复后复用'
                      : '复用已有'}
              </summary>
              <p className="hint">复用保留原分类、内容和测试记录。</p>
              <FormSelect
                label="如何处理"
                value={d.action}
                disabled={busy}
                options={[
                  { value: 'reuse', label: '复用已有用例' },
                  { value: 'restore', label: '恢复停用用例并复用' },
                  { value: 'include', label: '仍然新增' },
                  { value: 'ignore', label: '忽略本条' },
                ]}
                onChange={(action) =>
                  changeDecision(active, { action: action as Decision['action'] })
                }
              />
              {(active.matches.length > 1 || problem(active)) && (
                <FormSelect
                  label="选择已有用例"
                  value={String(d.targetId || '')}
                  disabled={busy}
                  options={[
                    { value: '', label: '请选择' },
                    ...active.matches.map((c) => ({
                      value: String(c.id),
                      label: `${c.number} / v${c.version}${c.lifecycle === 'RETIRED' ? ' · 停用' : ''}`,
                    })),
                  ]}
                  onChange={(value) =>
                    changeDecision(active, { targetId: value ? Number(value) : null })
                  }
                />
              )}
              {['include', 'ignore', 'restore'].includes(d.action) && (
                <label className="form-field">
                  原因
                  <input
                    maxLength={10000}
                    value={d.reason}
                    disabled={busy}
                    onChange={(e) => changeDecision(active, { reason: e.target.value })}
                  />
                </label>
              )}
            </details>
          )}
          <details className="evidence">
            <summary>需求依据</summary>
            <GenerationEvidence
              record={record}
              suggestion={record.suggestions.find((s) => s.key === active.key) || { evidence: [] }}
            />
          </details>
        </article>
      </div>
    </CaseDialog>
  );
}

export function GenerationApplicationResult({
  application,
  categories,
  onClose,
  onFailures,
}: {
  application: NonNullable<GenerationRecord['applications']>[number];
  categories: CaseCategory[];
  onClose: () => void;
  onFailures: () => void;
}) {
  const [page, setPage] = useState(1),
    count = (status: string) => application.items.filter((i) => i.status === status).length,
    ignored = application.items.filter(
      (i) => i.status === 'COMPLETED' && i.action === 'ignore',
    ).length,
    pages = Math.max(1, Math.ceil(application.items.length / 10)),
    current = Math.min(page, pages),
    status =
      (
        {
          QUEUED: '等待后台入库',
          RUNNING: '正在逐条入库',
          COMPLETED: '本批处理完成',
          FAILED: '本次提交未完成，已成功的用例保留',
        } as Record<string, string>
      )[application.status] || application.status;
  return (
    <CaseDialog
      title="批量审核结果"
      busy={false}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog generation-dialog"
      footer={
        <footer className="change-dialog-footer">
          <button onClick={onClose}>关闭</button>
          {count('FAILED') > 0 && <button onClick={onFailures}>查看失败清单</button>}
        </footer>
      }
    >
      <p className="notice" role="status">
        {status}。成功项会保留，不重复入库；可关闭后继续查看其他用例。
      </p>
      <div className="code-report-summary">
        <strong>成功 {count('COMPLETED') - ignored}条</strong>
        {!!ignored && <span>忽略 {ignored}条</span>}
        <span>失败 {count('FAILED')}条</span>
        <span>待处理 {count('PENDING') + count('RUNNING')}条</span>
      </div>
      {application.status === 'QUEUED' && (
        <p className="hint">若长时间没有更新，请检查后台Worker是否运行。</p>
      )}
      {application.error && (
        <p className="form-error" role="alert">
          {application.error}
        </p>
      )}
      {application.items.slice((current - 1) * 10, current * 10).map((i, n) => (
        <section className="evidence" key={n}>
          <strong>
            {String(i.key)} ·{' '}
            {(
              {
                COMPLETED: '已处理',
                FAILED: '失败',
                PENDING: '待处理',
                RUNNING: '处理中',
              } as Record<string, string>
            )[String(i.status)] || String(i.status)}
          </strong>
          <p className="hint">
            本次分类：
            {i.category_mode === 'SET'
              ? categories.find((c) => c.id === i.category_id)?.name ||
                `分类ID ${i.category_id}（需核对）`
              : i.category_mode === 'CLEAR'
                ? '未分类'
                : '保持原分类'}
          </p>
          {!!i.error && <p className="generation-failure">{String(i.error)}</p>}
        </section>
      ))}
      <nav className="generation-review-pagination" aria-label="入库结果分页">
        <span>
          {application.items.length}条 · 第{current}/{pages}页
        </span>
        <div className="row">
          <button disabled={current === 1} onClick={() => setPage(current - 1)}>
            上一页
          </button>
          <button disabled={current === pages} onClick={() => setPage(current + 1)}>
            下一页
          </button>
          <PageJump page={current} onChange={setPage} pages={pages} />
        </div>
      </nav>
    </CaseDialog>
  );
}
