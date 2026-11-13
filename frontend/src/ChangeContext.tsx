import { useEffect, useRef, useState } from 'react';
import { FormSelect } from './FormSelect';
import { generationCaseSnapshot } from './generationRead';
import { riskListing, riskDetailRequest } from './riskApi';
import { codeList, codeRequest, parseCodeDetail } from './codeAnalysisApi';
import { changeError } from './changeAnalysisApi';

export type HistorySelection = {
  module: 'REQUIREMENT_ANALYSIS' | 'CODE_REVIEW';
  report_id: number;
  item_key: string;
};
export function ChangeContext({
  projectId,
  onCases,
  onHistory,
  onSessionEnd,
}: {
  projectId: number;
  onCases: (ids: number[], versions: Record<string, number>) => void;
  onHistory: (items: HistorySelection[]) => void;
  onSessionEnd: () => void;
}) {
  const [caseRows, setCaseRows] = useState<
      { id: number; version: number; number: string; title: string }[]
    >([]),
    [caseIds, setCaseIds] = useState<number[]>([]),
    [reports, setReports] = useState<{ id: number; title: string }[]>([]),
    [module, setModule] = useState<HistorySelection['module']>('REQUIREMENT_ANALYSIS'),
    [reportId, setReportId] = useState(''),
    [problems, setProblems] = useState<{ key: string; title: string }[]>([]),
    [selected, setSelected] = useState<HistorySelection[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [more, setMore] = useState(false),
    [page, setPage] = useState(0);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  async function loadCases() {
    setBusy(true);
    setError('');
    try {
      const value = await generationCaseSnapshot(projectId, controller.current.signal);
      if (!controller.current.signal.aborted)
        setCaseRows(
          value.items.map((x) => ({
            id: x.id,
            version: x.version,
            number: x.number,
            title: x.title,
          })),
        );
    } catch (e) {
      if (!controller.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function loadReports() {
    setBusy(true);
    setError('');
    try {
      const root = `/api/projects/${projectId}`;
      const result =
        module === 'REQUIREMENT_ANALYSIS'
          ? await riskListing(
              `${root}/requirements/risk-reports?page=${page + 1}`,
              controller.current.signal,
            )
          : await codeList(`${root}/code-analysis?page=${page + 1}`, controller.current.signal);
      if (!controller.current.signal.aborted) {
        setReports((old) => [
          ...old,
          ...result.items
            .filter((r) => !('status' in r) || r.status === 'COMPLETED')
            .map((r) => ({ id: r.id, title: r.title })),
        ]);
        setPage((p) => p + 1);
        setMore(result.has_more);
      }
    } catch (e) {
      if (!controller.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function choose(id: string) {
    setReportId(id);
    setProblems([]);
    if (!id) return;
    setBusy(true);
    setError('');
    try {
      const root = `/api/projects/${projectId}`;
      if (module === 'REQUIREMENT_ANALYSIS') {
        const d = await riskDetailRequest(`${root}/requirements/risk-reports/${id}`, projectId, {
          signal: controller.current.signal,
        });
        if (!controller.current.signal.aborted)
          setProblems(d.report.risks.map((r) => ({ key: r.key, title: r.title })));
      } else {
        const d = await codeRequest(`${root}/code-analysis/${id}`, parseCodeDetail, {
          signal: controller.current.signal,
        });
        if (!controller.current.signal.aborted)
          setProblems(d.report?.findings.map((r) => ({ key: r.key, title: r.title })) || []);
      }
    } catch (e) {
      if (!controller.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <>
      <section className="evidence">
        <h3>现有用例</h3>
        <button type="button" className="small mt" disabled={busy} onClick={() => void loadCases()}>
          读取当前用例范围
        </button>
        <p className="hint">只带入勾选用例的内部ID与实际设计版本；建议不修改用例或测试记录。</p>
        <div className="code-file-tree mt">
          {caseRows.map((c) => (
            <label className="check-label" key={c.id}>
              <input
                type="checkbox"
                disabled={busy}
                checked={caseIds.includes(c.id)}
                onChange={(e) => {
                  const next = e.target.checked
                    ? [...caseIds, c.id]
                    : caseIds.filter((id) => id !== c.id);
                  setCaseIds(next);
                  onCases(
                    next,
                    Object.fromEntries(
                      caseRows
                        .filter((r) => next.includes(r.id))
                        .map((r) => [String(r.id), r.version]),
                    ),
                  );
                }}
              />
              {c.number} · {c.title} · v{c.version}
            </label>
          ))}
        </div>
      </section>
      <section className="evidence">
        <h3>历史报告与人工结论快照</h3>
        <FormSelect
          label="报告类型"
          value={module}
          disabled={busy}
          options={[
            { value: 'REQUIREMENT_ANALYSIS', label: '需求分析' },
            { value: 'CODE_REVIEW', label: '代码分析' },
          ]}
          onChange={(v) => {
            setModule(v as HistorySelection['module']);
            setReports([]);
            setReportId('');
            setProblems([]);
            setPage(0);
            setMore(false);
          }}
        />
        <button
          type="button"
          className="small mt"
          disabled={busy || (page > 0 && !more)}
          onClick={() => void loadReports()}
        >
          {page ? '加载更多报告' : '读取已完成报告'}
        </button>
        <FormSelect
          label="固定报告"
          value={reportId}
          disabled={busy}
          options={[
            { value: '', label: '请选择报告' },
            ...reports.map((r) => ({ value: String(r.id), label: r.title })),
          ]}
          onChange={(v) => void choose(v)}
        />
        {problems.map((p) => (
          <label className="check-label" key={p.key}>
            <input
              type="checkbox"
              disabled={busy}
              checked={selected.some(
                (s) =>
                  s.module === module && s.report_id === Number(reportId) && s.item_key === p.key,
              )}
              onChange={(e) => {
                const value = { module, report_id: Number(reportId), item_key: p.key };
                const next = e.target.checked
                  ? [...selected, value]
                  : selected.filter(
                      (s) =>
                        !(
                          s.module === value.module &&
                          s.report_id === value.report_id &&
                          s.item_key === value.item_key
                        ),
                    );
                setSelected(next);
                onHistory(next);
              }}
            />
            {p.key} · {p.title}
          </label>
        ))}
        {selected.map((s) => (
          <p className="hint" key={`${s.module}:${s.report_id}:${s.item_key}`}>
            {s.module === 'CODE_REVIEW' ? '代码' : '需求'}报告 #{s.report_id} / {s.item_key}{' '}
            <button
              type="button"
              className="link"
              onClick={() => {
                const next = selected.filter((v) => v !== s);
                setSelected(next);
                onHistory(next);
              }}
            >
              移除
            </button>
          </p>
        ))}
        <p className="hint">复核仅记录本次判断，不自动关闭历史问题；未带旧正文时不证明问题修复。</p>
      </section>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
