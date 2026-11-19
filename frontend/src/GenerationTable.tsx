import { Fragment, useId, useState } from 'react';
import { DESIGN_FIELDS } from './caseApi';
import type { Design } from './caseApi';
import {
  currentHandling,
  generationGroups,
  generationKinds,
  generationReady,
} from './generationPage';
import type { GenerationRecord, GenerationSuggestion } from './generationPage';

function problem(record: GenerationRecord, s: GenerationSuggestion, checked: string) {
  const h = currentHandling(record, s),
    d = h?.draft || s.design;
  if (['已应用', '已复用', '已忽略'].includes(h?.status || '')) return '';
  const failure = record.failures.find((f) => f.key === s.key);
  if (failure) return failure.reason;
  if (s.blocked && !h?.resolved) return s.reason || '需人工核对冲突或依据';
  const missing = (['title', 'steps', 'expected'] as const).filter((k) => !d[k].trim());
  if (['NEW', 'UPDATE'].includes(s.kind) && missing.length)
    return (
      '待补充：' +
      missing.map((k) => ({ title: '标题', steps: '步骤', expected: '预期' })[k]).join('、')
    );
  if (!s.evidence.length) return '本条没有保存来源引用，请核对固定依据。';
  return checked || (h?.status === '需人工确认' ? '请核对当前版本并保存修订后重试。' : '');
}

export function GenerationTable({
  record,
  rows,
  filtered,
  chosen,
  busy,
  issues,
  onChoose,
  onDetail,
  onReview,
  onEvidence,
  onAsk,
  onApplied,
  onResolve,
  duplicates,
  onBatchReview,
  onSelectRows,
}: {
  record: GenerationRecord;
  rows: GenerationSuggestion[];
  filtered: GenerationSuggestion[];
  chosen: string[];
  busy: boolean;
  issues: Record<string, string>;
  duplicates: string[];
  onChoose: (key: string, checked: boolean) => void;
  onDetail: (key: string) => void;
  onReview: (key: string) => void;
  onEvidence: (key: string, trigger: HTMLButtonElement) => void;
  onAsk: (key: string, feature: string) => void;
  onApplied: (key: string) => void;
  onResolve: (key: string) => void;
  onBatchReview: () => void;
  onSelectRows: (rows: GenerationSuggestion[]) => void;
}) {
  const [expanded, setExpanded] = useState<string[]>([]),
    [collapsed, setCollapsed] = useState<string[]>([]),
    id = useId();
  const toggle = (values: string[], key: string) =>
    values.includes(key) ? values.filter((v) => v !== key) : [...values, key];
  const allExpanded = rows.length > 0 && rows.every((s) => expanded.includes(s.key));
  function cell(s: GenerationSuggestion, field: 'preconditions' | 'steps' | 'expected') {
    const d = currentHandling(record, s)?.draft || s.design,
      changed = s.kind === 'UPDATE' && s.before && s.before[field] !== d[field],
      missing = ['NEW', 'UPDATE'].includes(s.kind) && field !== 'preconditions' && !d[field].trim();
    return (
      <>
        {changed && <div className="cg-table-diff">已修改</div>}
        <div className={`cg-table-value${missing ? ' is-missing' : ''}`}>
          {d[field] || (missing ? '必填内容待补充' : '—')}
        </div>
        {changed && (
          <details className="cg-table-old">
            <summary>查看固定旧值</summary>
            <p>{s.before![field] || '（空）'}</p>
          </details>
        )}
      </>
    );
  }
  return (
    <>
      <div className="generation-bulk">
        <div className="row">
          <button
            className="small"
            disabled={!rows.some((s) => s.kind !== 'RETIRE' && generationReady(record, s))}
            onClick={() => onSelectRows(rows)}
          >
            选择当前页
          </button>
          <button
            className="small"
            disabled={!filtered.some((s) => s.kind !== 'RETIRE' && generationReady(record, s))}
            onClick={() => onSelectRows(filtered)}
          >
            选择筛选全部（跨页）
          </button>
          <button
            className="small"
            disabled={!rows.length}
            onClick={() =>
              setExpanded((keys) =>
                allExpanded
                  ? keys.filter((k) => !rows.some((s) => s.key === k))
                  : [...new Set([...keys, ...rows.map((s) => s.key)])],
              )
            }
          >
            展开 / 收起本页全文
          </button>
        </div>
        <span className="hint">
          当前筛选可批量选择
          {filtered.filter((s) => s.kind !== 'RETIRE' && generationReady(record, s)).length}
          条；未解决冲突、停用及已处理项排除
        </span>
        <button className="primary small" disabled={busy || !chosen.length} onClick={onBatchReview}>
          审核所选（{chosen.length}）
        </button>
      </div>
      <div className="cg-mobile-table-note">
        可横向滚动查看前置条件、步骤和预期；展开全文后在当前行连续阅读。
      </div>
      <div className="cg-table-scroll" tabIndex={0} aria-label="用例审阅表格，可横向滚动">
        <table className="cg-review-table">
          <caption className="screen-reader">
            按功能分组的用例建议，展开查看全文，勾选后批量审核
          </caption>
          <colgroup>
            {[4, 21, 16, 23, 24, 12].map((n) => (
              <col key={n} style={{ width: `${n}%` }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {['选择', '用例 / 状态', '前置条件', '操作步骤', '预期结果', '操作'].map(
                (name, i) => (
                  <th key={name} scope="col" className={i === 0 ? 'cg-select-cell' : ''}>
                    {name}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {[...generationGroups(rows)].map(([feature, group]) => {
              const all = filtered.filter((s) => s.function === feature),
                closed = collapsed.includes(feature);
              return (
                <Fragment key={feature}>
                  <tr className="cg-group-head">
                    <td colSpan={6}>
                      <div className="between">
                        <button
                          className="ghost small"
                          aria-expanded={!closed}
                          onClick={() => setCollapsed((v) => toggle(v, feature))}
                        >
                          <span className="cg-group-arrow" aria-hidden="true">
                            {closed ? '▸' : '▾'}
                          </span>
                          <strong>{feature || '未归类'}</strong>
                          <small>
                            本页 {group.length} / 共 {all.length}条 · 待审阅{' '}
                            {
                              all.filter(
                                (s) =>
                                  (currentHandling(record, s)?.status || '待审阅') === '待审阅',
                              ).length
                            }{' '}
                            · 已入库{' '}
                            {
                              all.filter((s) =>
                                ['已应用', '已复用'].includes(
                                  currentHandling(record, s)?.status || '',
                                ),
                              ).length
                            }
                          </small>
                        </button>
                        <button
                          className="link small"
                          disabled={
                            !group.some((s) => s.kind !== 'RETIRE' && generationReady(record, s))
                          }
                          onClick={() => onSelectRows(group)}
                        >
                          选择本组（本页）
                        </button>
                      </div>
                    </td>
                  </tr>
                  {!closed &&
                    group.map((s) => {
                      const h = currentHandling(record, s),
                        d = h?.draft || s.design,
                        done = ['已应用', '已复用'].includes(h?.status || ''),
                        issue = problem(record, s, issues[s.key] || ''),
                        open = expanded.includes(s.key),
                        moreId = `${id}-${s.key}`;
                      return (
                        <Fragment key={s.key}>
                          <tr
                            className={`cg-table-row${open ? ' is-expanded' : ''}${chosen.includes(s.key) ? ' is-selected' : ''}${done ? ' is-done' : ''}${issue ? ' is-problem' : ''}`}
                            data-cg-row={s.key}
                          >
                            <td className="cg-select-cell">
                              <input
                                type="checkbox"
                                aria-label={`选择建议 ${s.key}`}
                                checked={chosen.includes(s.key)}
                                disabled={!generationReady(record, s)}
                                onChange={(e) => onChoose(s.key, e.target.checked)}
                              />
                            </td>
                            <td>
                              <div className="cg-table-key">
                                {!s.nativeResultId && <span>{s.key}</span>}
                                <span>{d.priority || '未设优先级'}</span>
                                {h &&
                                  DESIGN_FIELDS.some(
                                    (field) => h.draft[field] !== s.design[field],
                                  ) && <span>已修订</span>}
                              </div>
                              <strong className="cg-table-title">{d.title || '标题待补充'}</strong>
                              <div className="cg-table-tags">
                                <span
                                  className={`badge ${s.kind === 'UPDATE' ? 'orange' : 'green'}`}
                                >
                                  {generationKinds[s.kind]}
                                </span>
                                <span className={`badge ${done ? 'green' : issue ? 'orange' : ''}`}>
                                  {done ? '已入库' : h?.status || '待审阅'}
                                </span>
                                {issue && <span className="badge orange">需处理</span>}
                              </div>
                              {issue && <p className="cg-table-problem">{issue}</p>}
                            </td>
                            <td>{cell(s, 'preconditions')}</td>
                            <td>{cell(s, 'steps')}</td>
                            <td>{cell(s, 'expected')}</td>
                            <td>
                              <div className="cg-table-actions">
                                <button
                                  className="link"
                                  aria-expanded={open}
                                  aria-controls={moreId}
                                  onClick={() => setExpanded((v) => toggle(v, s.key))}
                                >
                                  {open ? '收起全文' : '展开全文'}
                                </button>
                                <button
                                  className="link"
                                  disabled={busy}
                                  onClick={() => onDetail(s.key)}
                                >
                                  详情修订
                                </button>
                                <button
                                  className="link"
                                  onClick={(e) => onEvidence(s.key, e.currentTarget)}
                                >
                                  固定依据 · {s.evidence.length}
                                </button>
                                {(!!issues[s.key] || duplicates.includes(s.key)) && (
                                  <button
                                    className="link"
                                    disabled={busy}
                                    onClick={() => onResolve(s.key)}
                                  >
                                    {duplicates.includes(s.key) ? '处理重复' : '处理入库问题'}
                                  </button>
                                )}
                                {done ? (
                                  <button className="link" onClick={() => onApplied(s.key)}>
                                    应用记录
                                  </button>
                                ) : (
                                  s.kind !== 'RETIRE' &&
                                  generationReady(record, s) &&
                                  !issue && (
                                    <button
                                      className="cg-row-review"
                                      disabled={busy}
                                      onClick={() => onReview(s.key)}
                                    >
                                      审核入库
                                    </button>
                                  )
                                )}
                              </div>
                            </td>
                          </tr>
                          <tr className="cg-table-more" id={moreId} hidden={!open}>
                            <td colSpan={6}>
                              <div className="cg-table-more-grid">
                                {(
                                  [
                                    ['description', '用例描述'],
                                    ['module', '功能模块'],
                                    ['structure', '功能结构'],
                                    ['case_type', '用例类型'],
                                    ['data_requirements', '测试数据要求'],
                                    ['cleanup', '清理要求'],
                                    ['remark', '备注'],
                                  ] as [keyof Design, string][]
                                ).map(([field, label]) => (
                                  <section key={field}>
                                    <h4>{label}</h4>
                                    <p>{d[field] || '—'}</p>
                                  </section>
                                ))}
                                <section>
                                  <h4>建议说明</h4>
                                  <p>{s.reason || '—'}</p>
                                </section>
                                <div className="cg-more-basis">
                                  <span className="hint">
                                    {s.caseId
                                      ? `目标用例 ${s.caseId} · 固定 v${s.baseVersion}`
                                      : '新增用例编号在确认入库后分配'}{' '}
                                    · {s.evidence.length}条固定来源
                                  </span>
                                  <button
                                    className="link"
                                    onClick={(e) => onEvidence(s.key, e.currentTarget)}
                                  >
                                    查看本条需求 / 原型摘录
                                  </button>
                                  <button className="link" onClick={() => onAsk(s.key, s.function)}>
                                    引用提问
                                  </button>
                                </div>
                              </div>
                            </td>
                          </tr>
                        </Fragment>
                      );
                    })}
                </Fragment>
              );
            })}
            {!rows.length && (
              <tr>
                <td colSpan={6}>
                  <div className="empty">没有匹配建议，可调整筛选或搜索条件。</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
