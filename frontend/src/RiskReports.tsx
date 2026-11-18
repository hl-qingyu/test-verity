import { AnalysisCandidateReview } from './AnalysisCandidateReview';
import { useCachedView } from './pageViewCache';
import type { PageViewCache } from './pageViewCache';
import type { AISelection } from './aiConfiguration';
import { callModeName, readSelectedAI } from './aiConfiguration';
import { AIConfigurationSummary } from './AIConfigurationSummary';
import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import { AnalysisRecordDelete } from './AnalysisRecordDelete';
import { PageJump } from './PageJump';
import { AcceptancePanel } from './AnalysisAcceptance';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Project } from './Projects';
import type { OverviewTarget } from './OverviewEntry';
import { apiDownload, apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import { FilePicker } from './FilePicker';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { PrototypeLinkPages } from './PrototypeLinkPages';
import type { LinkSelection } from './PrototypeLinkPages';
import { Icon } from './Icon';
import { OriginalPreview } from './Documents';
import {
  outcomes,
  parseRiskInput,
  parseRiskReport,
  readRiskFile,
  riskAnalyses,
  riskCatalog,
  riskDetailRequest,
  riskError,
  riskLevels,
  riskListing,
  riskOptions,
  riskStates,
  riskTaskFailure,
  riskTypes,
} from './riskApi';
import type {
  Evidence,
  Input,
  MaterialOption,
  ReportItem,
  Risk,
  RiskDetail,
  RiskReport,
  RiskState,
  SourceBinding,
  CatalogItem,
  RiskAnalysisTask,
  RiskCatalog,
  ReviewWarning,
} from './riskApi';
import './risk-reports.css';
import './requirement-ui.css';

const time = (value: string) => new Date(value).toLocaleString();
const warningNames: Record<string, string> = {
  invalid_coverage: '片段的功能与风险标签待核对',
  evidence_excerpt_mismatch: '摘录未匹配固定原文',
  evidence_location_mismatch: '证据位置与固定输入不一致',
  missing_coverage: '功能或风险缺少覆盖标记',
};
const warningText = (warning: ReviewWarning) =>
  `${warning.risk_key || warning.source_id || '整体'} · ${warning.segment_id || warning.path}：${warningNames[warning.code] || warning.code}`;
const taskStates = {
  QUEUED: '排队中',
  RUNNING: '分析中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
} as const;
function status(detail: RiskDetail, key: string): RiskState {
  return detail.handling.find((h) => h.risk_key === key)?.status || 'PENDING';
}
function Badge({ children, tone = '' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge risk-badge ${tone}`}>{children}</span>;
}
function saveFile(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob),
    a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function EvidenceList({
  evidence,
  detail,
  onSource,
}: {
  evidence: Evidence[];
  detail: RiskDetail;
  onSource: (id: string) => void;
}) {
  return (
    <div className="stack">
      {evidence.map((e, i) => (
        <div className="evidence risk-evidence" key={i}>
          <strong>
            {detail.input.materials.find((m) => m.source_id === e.source_id)?.name || e.source_id}
          </strong>
          <p className="hint">
            {e.source_id} · {e.location}
          </p>
          {e.excerpt && <blockquote>{e.excerpt}</blockquote>}
          {e.observation && <p>{e.observation}</p>}
          <button className="link small" type="button" onClick={() => onSource(e.source_id)}>
            查看输入与关联原件
          </button>
        </div>
      ))}
    </div>
  );
}

type RiskProps = {
  pageCache?: PageViewCache;
  project: Project | null;
  onSessionEnd: () => void;
  overviewTarget?: OverviewTarget | null;
};
export function RiskReports(props: RiskProps) {
  const [deletionVersion, setDeletionVersion] = useState(0);
  return (
    <RiskWorkspace
      key={`${props.project?.id}:${deletionVersion}`}
      {...props}
      overviewTarget={deletionVersion ? null : props.overviewTarget}
      onRecordDeleted={() => {
        props.pageCache?.delete('selected');
        setDeletionVersion((v) => v + 1);
      }}
    />
  );
}
function RiskWorkspace({
  onRecordDeleted,
  pageCache,
  project,
  onSessionEnd,
  overviewTarget,
}: {
  pageCache?: PageViewCache;
  onRecordDeleted: () => void;
  project: Project | null;
  onSessionEnd: () => void;
  overviewTarget?: OverviewTarget | null;
}) {
  const base = `/api/projects/${project?.id}/requirements/risk-reports`;
  const [items, setItems] = useState<ReportItem[]>([]),
    [page, setPage] = useCachedView(pageCache, 'page', 1),
    [more, setMore] = useState(false),
    [selected, setSelected] = useCachedView<number | null>(
      pageCache,
      'selected',
      overviewTarget?.recordType === 'report' ? overviewTarget.id : null,
    ),
    [detail, setDetail] = useState<RiskDetail | null>(null),
    [loading, setLoading] = useState(true),
    [detailLoading, setDetailLoading] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [reload, setReload] = useState(0),
    [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false),
    [acceptanceReport, setAcceptanceReport] = useState(''),
    [starting, setStarting] = useState<RiskAnalysisTask | true | null>(null),
    [history, setHistory] = useState(false),
    [scopeOpen, setScopeOpen] = useState(false),
    [analysisQuery, setAnalysisQuery] = useCachedView(pageCache, 'analysisQuery', ''),
    [riskKey, setRiskKey] = useState<string | null>(null),
    [sourceKey, setSourceKey] = useState<string | null>(null),
    [tab, setTab] = useCachedView<'risks' | 'functions' | 'report' | 'sources'>(
      pageCache,
      'tab',
      'risks',
    ),
    [feature, setFeature] = useCachedView(pageCache, 'feature', ''),
    [level, setLevel] = useCachedView(pageCache, 'level', ''),
    [state, setState] = useCachedView(pageCache, 'state', '');
  const [catalog, setCatalog] = useState<RiskCatalog | null>(null),
    [catalogPage, setCatalogPage] = useCachedView(pageCache, 'catalogPage', 1),
    [catalogSource, setCatalogSource] = useCachedView(
      pageCache,
      'catalogSource',
      overviewTarget?.recordType === 'report' ? String(overviewTarget.id) : '',
    ),
    [catalogFunction, setCatalogFunction] = useCachedView(pageCache, 'catalogFunction', ''),
    [catalogLevel, setCatalogLevel] = useCachedView(pageCache, 'catalogLevel', ''),
    [catalogState, setCatalogState] = useCachedView(
      pageCache,
      'catalogState',
      overviewTarget?.state || '',
    ),
    [catalogRisk, setCatalogRisk] = useState<CatalogItem | null>(null),
    [tasks, setTasks] = useState<RiskAnalysisTask[]>([]),
    [catalogLoading, setCatalogLoading] = useState(false);
  const abort = useRef(new AbortController()),
    pending = useRef(false),
    hadActiveTasks = useRef(false);
  useEffect(() => {
    const c = new AbortController();
    abort.current = c;
    return () => c.abort();
  }, []);
  useEffect(() => {
    if (!project) {
      setLoading(false);
      return;
    }
    const c = new AbortController();
    setLoading(true);
    setError('');
    riskListing(`${base}?page=${page}`, c.signal)
      .then((v) => {
        if (!c.signal.aborted) {
          setItems(v.items);
          setMore(v.has_more);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(riskError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [base, project, page, reload, onSessionEnd]);
  useEffect(() => {
    if (!selected || !project) return;
    const c = new AbortController();
    setDetailLoading(true);
    setDetail(null);
    riskDetailRequest(`${base}/${selected}`, project.id, { signal: c.signal })
      .then((v) => {
        if (!c.signal.aborted && v.id === selected) setDetail(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(riskError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setDetailLoading(false);
      });
    return () => c.abort();
  }, [base, selected, project, reload, onSessionEnd]);
  useEffect(() => {
    if (!project) return;
    const c = new AbortController();
    const query = new URLSearchParams({ page: String(catalogPage) });
    setCatalogLoading(true);
    if (catalogSource) query.set('source', catalogSource);
    if (catalogFunction) query.set('function', catalogFunction);
    if (catalogLevel) query.set('severity', catalogLevel);
    if (catalogState) query.set('state', catalogState);
    riskCatalog(`/api/projects/${project.id}/requirements/risk-reports-catalog?${query}`, c.signal)
      .then((value) => {
        if (!c.signal.aborted) {
          setCatalog(value);
          if (catalogPage > value.pages) setCatalogPage(value.pages);
        }
      })
      .catch((reason) => {
        if (
          !c.signal.aborted &&
          reason instanceof Error &&
          ['not_authenticated', 'project_not_found'].includes(reason.message)
        ) {
          setCatalog(null);
          setDetail(null);
          setTasks([]);
          setItems([]);
        }
        if (!c.signal.aborted) setError(riskError(reason, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setCatalogLoading(false);
      });
    return () => c.abort();
  }, [
    project,
    catalogPage,
    catalogSource,
    catalogFunction,
    catalogLevel,
    catalogState,
    setCatalogPage,
    reload,
    onSessionEnd,
  ]);
  useEffect(() => {
    if (!project) return;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function loadTasks() {
      try {
        const value = await riskAnalyses(
          `/api/projects/${project!.id}/requirements/risk-analyses`,
          c.signal,
        );
        if (!c.signal.aborted) {
          setTasks(value);
          if (
            overviewTarget?.recordType === 'task' &&
            !value.some((t) => t.id === overviewTarget.id)
          )
            setError('该分析记录不存在或已无访问权限，请返回模块重新选择。');
          const active = value.some((item) => ['QUEUED', 'RUNNING'].includes(item.status));
          if (hadActiveTasks.current && !active) setReload((current) => current + 1);
          hadActiveTasks.current = active;
          if (active) timer = setTimeout(loadTasks, 2500);
        }
      } catch (reason) {
        if (!c.signal.aborted) setError(riskError(reason, onSessionEnd));
      }
    }
    void loadTasks();
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [project, reload, onSessionEnd, overviewTarget]);
  async function exportJSON(kind: 'input' | 'report') {
    if (!detail || pending.current) return;
    pending.current = true;
    setBusy(true);
    try {
      const blob = await apiDownload(`${base}/${detail.id}/export?kind=${kind}`, {
        signal: abort.current.signal,
      });
      if (!abort.current.signal.aborted) saveFile(`${kind}.json`, blob);
    } catch (e) {
      if (!abort.current.signal.aborted) setError(riskError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (!abort.current.signal.aborted) setBusy(false);
    }
  }
  async function exportCatalog() {
    if (!project || pending.current) return;
    const query = new URLSearchParams();
    if (catalogSource) query.set('source', catalogSource);
    if (catalogFunction) query.set('function', catalogFunction);
    if (catalogLevel) query.set('severity', catalogLevel);
    if (catalogState) query.set('state', catalogState);
    pending.current = true;
    setBusy(true);
    try {
      const blob = await apiDownload(
        `/api/projects/${project.id}/requirements/risk-reports-export?${query}`,
        { signal: abort.current.signal },
      );
      saveFile('需求风险清单.md', blob);
    } catch (reason) {
      setError(riskError(reason, onSessionEnd));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  async function cancelAnalysis(task: RiskAnalysisTask) {
    if (!project) return;
    setBusy(true);
    setError('');
    try {
      await apiRequest(`/api/projects/${project.id}/requirements/risk-analyses/${task.id}/cancel`, {
        method: 'POST',
      });
      setReload((value) => value + 1);
    } catch (reason) {
      setError(riskError(reason, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  async function downloadCandidate(task: RiskAnalysisTask) {
    if (!project || busy || !task.candidate_available) return;
    setBusy(true);
    setError('');
    try {
      const blob = await apiDownload(
        `/api/projects/${project.id}/requirements/risk-analyses/${task.id}/candidate`,
        { signal: abort.current.signal },
      );
      if (!abort.current.signal.aborted)
        saveFile(`requirement-analysis-${task.id}-ai-candidate.txt`, blob);
    } catch (reason) {
      if (!abort.current.signal.aborted) setError(riskError(reason, onSessionEnd));
    } finally {
      if (!abort.current.signal.aborted) setBusy(false);
    }
  }
  async function revalidateCandidate(task: RiskAnalysisTask) {
    if (!project || busy || !task.can_revalidate) return;
    setBusy(true);
    setError('');
    try {
      await apiRequest(
        `/api/projects/${project.id}/requirements/risk-analyses/${task.id}/revalidate`,
        { method: 'POST', signal: abort.current.signal },
      );
      if (!abort.current.signal.aborted) setReload((value) => value + 1);
    } catch (reason) {
      if (!abort.current.signal.aborted) setError(riskError(reason, onSessionEnd));
    } finally {
      if (!abort.current.signal.aborted) setBusy(false);
    }
  }
  function openScope(reportId: number) {
    setDetail(null);
    setSelected(reportId);
    setScopeOpen(true);
  }
  if (!project)
    return (
      <section className="panel empty">
        <h2>请先选择项目</h2>
      </section>
    );
  const records = catalog
    ? [
        ...catalog.reports.map((item) => ({ ...item, kind: 'report' as const })),
        ...tasks
          .filter((task) => !task.report_id)
          .map((task) => ({ ...task, kind: 'task' as const })),
      ]
        .filter((item) => {
          const materialText =
            item.kind === 'report'
              ? item.materials.map((material) => `${material.name} ${material.version}`).join(' ')
              : '';
          return (
            (!overviewTarget ||
              overviewTarget.recordType !== 'task' ||
              (item.kind === 'task'
                ? item.id === overviewTarget.id
                : item.id === tasks.find((t) => t.id === overviewTarget.id)?.report_id)) &&
            `${item.title} ${item.id} ${materialText}`
              .toLowerCase()
              .includes(analysisQuery.toLowerCase())
          );
        })
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    : [];
  const report = detail?.report,
    risk = report?.risks.find((item) => item.key === riskKey),
    rows =
      report?.risks.filter(
        (item) =>
          (!feature || item.function_keys.includes(feature)) &&
          (!level || item.severity === level) &&
          (!state || (detail && status(detail, item.key) === state)),
      ) || [],
    showLegacyReport = false;
  function openSource(id: string) {
    setSourceKey(id);
  }
  return (
    <div className="risk-page requirement-ui">
      <header className="page-head">
        <div>
          <h1>需求分析</h1>
          <p>汇总各次分析的功能与风险。</p>
        </div>
        <div className="row">
          <button className="primary" onClick={() => setStarting(true)}>
            新建分析会话
          </button>
          {catalog?.reports[0] ? (
            <Link className="action ghost" to={`/requirements/chat/${catalog.reports[0].id}`}>
              历史会话
            </Link>
          ) : (
            <button className="ghost" disabled>
              历史会话
            </button>
          )}
          <button className="ghost" onClick={() => setImporting(true)}>
            <Icon name="upload" />
            导入分析结果
          </button>
        </div>
      </header>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="doc-note" role="status">
          {notice}
        </p>
      )}
      {loading && <p role="status">正在加载分析记录…</p>}
      {project && catalog && catalog.reports.length > 0 && (
        <section className="aa-requirement-record">
          <FormSelect
            label="AI结果指标 · 选择分析记录"
            value={String(acceptanceReport || catalogSource || selected || catalog.reports[0].id)}
            options={catalog.reports.map((r) => ({
              value: String(r.id),
              label: `#${r.id} · ${r.title}`,
            }))}
            onChange={setAcceptanceReport}
          />
          <AcceptancePanel
            refreshKey={reload}
            projectId={project.id}
            module="requirements"
            recordId={Number(
              acceptanceReport || catalogSource || selected || catalog.reports[0].id,
            )}
            onSessionEnd={onSessionEnd}
          />
        </section>
      )}
      {catalog && (catalog.reports.length || tasks.length) > 0 && (
        <>
          <section className="panel panel-pad ra-overview">
            <div className="between ra-heading">
              <div>
                <h2>{catalogSource ? '按来源分析筛选' : '累计功能风险清单'}</h2>
                <p className="hint">
                  已入库 {catalog.overview.reports} 次分析 · {catalog.overview.functions} 个功能项 ·{' '}
                  {catalog.overview.risks} 条风险
                </p>
                {catalogSource && (
                  <p className="hint">
                    当前来源：
                    {catalog.reports.find((item) => item.id === Number(catalogSource))?.title} · #
                    {catalogSource}
                  </p>
                )}
              </div>
              <div className="row">
                {catalogSource && (
                  <button
                    className="ghost"
                    onClick={() => {
                      setCatalogSource('');
                      setCatalogFunction('');
                      setCatalogPage(1);
                    }}
                  >
                    查看全部分析
                  </button>
                )}
                <button
                  className="primary small"
                  disabled={busy || !catalog.total}
                  onClick={() => void exportCatalog()}
                >
                  导出风险清单
                </button>
              </div>
            </div>
            <div className="ra-stats">
              <span>
                <strong>{catalog.overview.high}</strong> 高风险
              </span>
              <span>
                <strong>{catalog.overview.medium}</strong> 中风险
              </span>
              <span>
                <strong>{catalog.overview.low}</strong> 低风险
              </span>
              <span>
                <strong>{catalog.overview.pending}</strong> 待处理
              </span>
            </div>
            <details
              className="ra-conclusion"
              open={overviewTarget?.recordType === 'task' ? true : undefined}
            >
              <summary>
                分析记录 · {catalog.reports.length + tasks.filter((task) => !task.report_id).length}{' '}
                次（展开查看各次资料、结论和对话）
              </summary>
              <label className="field-label mt">
                查找分析记录
                <input
                  type="search"
                  value={analysisQuery}
                  onChange={(event) => setAnalysisQuery(event.target.value)}
                  placeholder="名称、资料、版本或编号"
                />
              </label>
              <div className="ra-table-scroll" tabIndex={0} role="region" aria-label="分析记录列表">
                <table>
                  <thead>
                    <tr>
                      <th>分析名称</th>
                      <th>需求 / 原型版本</th>
                      <th>时间 / 发起人</th>
                      <th>状态</th>
                      <th>风险</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((record) => (
                      <tr key={`${record.kind}-${record.id}`}>
                        <td>
                          <strong>{record.title}</strong>
                          <p>
                            <AIConfigurationSummary
                              value={
                                record.kind === 'task'
                                  ? record.ai
                                  : tasks.find((t) => t.report_id === record.id)?.ai
                              }
                            />
                          </p>
                          <p className="hint">#{record.id}</p>
                        </td>
                        <td>
                          {record.kind === 'report'
                            ? record.materials.map((material) => (
                                <div key={`${material.name}-${material.version}`}>
                                  {material.name} · {material.version}
                                </div>
                              ))
                            : `${record.selections.length} 份固定资料`}
                        </td>
                        <td>
                          {time(record.created_at)}
                          <p className="hint">{record.created_by}</p>
                        </td>
                        <td>
                          <Badge>
                            {record.kind === 'report'
                              ? outcomes[record.outcome]
                              : taskStates[record.status]}
                          </Badge>
                          {record.kind === 'task' && record.error_code && (
                            <p className="form-error">{riskTaskFailure(record.error_code)}</p>
                          )}
                          {record.kind === 'report' &&
                          tasks.find((task) => task.report_id === record.id)
                            ?.function_risk_corrections.length ? (
                            <p className="hint">已对齐功能与风险关联</p>
                          ) : null}
                          {record.kind === 'report' && record.review_warning_count > 0 && (
                            <p className="hint">{record.review_warning_count} 处待人工核对</p>
                          )}
                        </td>
                        <td>{record.kind === 'report' ? `${record.risks} 项风险` : '尚无结果'}</td>
                        <td>
                          <div className="ra-record-actions">
                            {record.kind === 'report' && (
                              <button
                                className="small"
                                onClick={() => {
                                  setCatalogSource(String(record.id));
                                  setCatalogFunction('');
                                  setCatalogPage(1);
                                }}
                              >
                                筛选本次清单
                              </button>
                            )}
                            <AnalysisRecordDelete
                              key={`${record.kind}:${record.id}`}
                              base={`/api/projects/${project.id}/requirements/${record.kind === 'report' ? 'risk-reports' : 'risk-analyses'}`}
                              id={record.id}
                              projectId={project.id}
                              onDeleted={onRecordDeleted}
                              onSessionEnd={onSessionEnd}
                              canDelete={record.can_delete}
                            />
                            {record.kind === 'report' && (
                              <button className="ghost small" onClick={() => openScope(record.id)}>
                                资料与结论
                              </button>
                            )}
                            {record.kind === 'report' && (
                              <Link className="action link" to={`/requirements/chat/${record.id}`}>
                                需求分析对话
                              </Link>
                            )}
                            {record.kind === 'task' &&
                              ['FAILED', 'CANCELLED'].includes(record.status) && (
                                <button className="small" onClick={() => setStarting(record)}>
                                  重新发起（调用AI）
                                </button>
                              )}
                            {record.kind === 'task' && record.candidate_available && (
                              <AnalysisCandidateReview
                                endpoint={`/api/projects/${project.id}/requirements/risk-analyses/${record.id}/candidate-review`}
                                onSessionEnd={onSessionEnd}
                              />
                            )}
                            {record.kind === 'task' && record.candidate_available && (
                              <button
                                className="ghost small"
                                disabled={busy}
                                onClick={() => void downloadCandidate(record)}
                              >
                                下载AI候选
                              </button>
                            )}
                            {record.kind === 'task' && record.can_revalidate && (
                              <button
                                className="small"
                                disabled={busy}
                                onClick={() => void revalidateCandidate(record)}
                              >
                                重新校验候选（不调用AI）
                              </button>
                            )}
                            {record.kind === 'task' && record.can_cancel && (
                              <button
                                className="danger small"
                                disabled={busy}
                                onClick={() => void cancelAnalysis(record)}
                              >
                                取消分析
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {!records.length && (
                      <tr>
                        <td colSpan={6}>没有匹配的分析记录。</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </details>
          </section>
          <div className="risk-workspace">
            <aside className="panel risk-functions">
              <div className="panel-head">
                <h2>功能范围</h2>
                <Badge>{catalog.functions.length}</Badge>
              </div>
              <button
                className={`risk-function ${!catalogFunction ? 'active' : ''}`}
                onClick={() => {
                  setCatalogFunction('');
                  setCatalogPage(1);
                }}
              >
                全部功能
              </button>
              {catalog.functions
                .filter((item) => !catalogSource || item.report_id === Number(catalogSource))
                .map((item) => (
                  <button
                    className={`risk-function ${catalogFunction === item.id ? 'active' : ''}`}
                    key={item.id}
                    onClick={() => {
                      setCatalogFunction(item.id);
                      setCatalogPage(1);
                    }}
                  >
                    <span>
                      {item.name}
                      <small className="hint">
                        {catalog.reports.find((report) => report.id === item.report_id)?.title} · #
                        {item.report_id}
                      </small>
                    </span>
                    <Badge>{item.risk_count}</Badge>
                  </button>
                ))}
            </aside>
            <section className="panel risk-list">
              <div className="panel-head">
                <h2>功能风险清单</h2>
                <Badge>{catalog.total} 项</Badge>
              </div>
              <div className="risk-filters">
                <div className="row">
                  <span className="hint">等级</span>
                  {[
                    ['', '全部等级'],
                    ...Object.entries(riskLevels).map(([value, label]) => [value, `${label}风险`]),
                  ].map(([value, label]) => (
                    <button
                      className={catalogLevel === value ? 'primary small' : 'ghost small'}
                      key={value}
                      onClick={() => {
                        setCatalogLevel(value);
                        setCatalogPage(1);
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="row">
                  <span className="hint">处理</span>
                  {[['', '全部'], ...Object.entries(riskStates)].map(([value, label]) => (
                    <button
                      className={catalogState === value ? 'primary small' : 'ghost small'}
                      key={value}
                      onClick={() => {
                        setCatalogState(value);
                        setCatalogPage(1);
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              {catalog.items.map((item) => {
                const functionKey = item.functions[0]?.key || '';
                return (
                  <article className="risk-card" key={item.id}>
                    <div className="row">
                      <Badge tone={item.risk.severity}>{riskLevels[item.risk.severity]}</Badge>
                      <Badge>{riskTypes[item.risk.type]}</Badge>
                      <span className="hint">
                        {item.risk_key} · {item.functions.map((value) => value.name).join('、')}
                      </span>
                      <span className="risk-card-status">
                        <Badge>{riskStates[item.status]}</Badge>
                      </span>
                    </div>
                    <h3>{item.risk.title}</h3>
                    {item.review_warnings.length > 0 && (
                      <p className="hint">{item.review_warnings.length} 处依据待核对</p>
                    )}
                    <p>{item.risk.description}</p>
                    <p className="hint">
                      来源分析：{item.report_title} · #{item.report_id} · {time(item.created_at)}
                    </p>
                    <div className="risk-impact">
                      <strong>可能影响</strong>
                      <span>{item.risk.impact}</span>
                    </div>
                    <div className="between">
                      <span className="hint">{item.risk.evidence.length} 处依据</span>
                      <div className="row">
                        {functionKey && (
                          <Link
                            className="action ghost small"
                            to={`/requirements/chat/${item.report_id}?function=${encodeURIComponent(functionKey)}&risk=${encodeURIComponent(item.risk_key)}`}
                          >
                            追问
                          </Link>
                        )}
                        <button className="link" onClick={() => setCatalogRisk(item)}>
                          查看依据与处理
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
              {!catalog.items.length && (
                <div className="risk-empty">
                  <h3>当前范围没有可展示的风险</h3>
                  <p>未完成的分析尚无结果。</p>
                  <button
                    onClick={() => {
                      setCatalogFunction('');
                      setCatalogLevel('');
                      setCatalogState('');
                      setCatalogPage(1);
                    }}
                  >
                    清空筛选
                  </button>
                </div>
              )}
              {!!catalog.total && (
                <nav className="panel-pad between" aria-label="风险清单分页">
                  <span className="hint">
                    共 {catalog.total} 条 · 每页 10 条 · 第 {catalog.page} / {catalog.pages} 页
                  </span>
                  <div className="row">
                    <button
                      className="small"
                      disabled={catalogLoading || catalog.page <= 1}
                      onClick={() => setCatalogPage((value) => value - 1)}
                    >
                      上一页
                    </button>
                    <button
                      className="small"
                      disabled={catalogLoading || catalog.page >= catalog.pages}
                      onClick={() => setCatalogPage((value) => value + 1)}
                    >
                      下一页
                    </button>
                    <PageJump
                      page={catalog.page}
                      onChange={setCatalogPage}
                      pages={catalog.pages}
                      disabled={catalogLoading}
                    />
                  </div>
                </nav>
              )}
            </section>
          </div>
        </>
      )}
      {!loading && catalog && !catalog.reports.length && !tasks.length && (
        <section className="panel risk-empty">
          <span className="risk-eyebrow">需求完善度审查</span>
          <h2>先找到问题，再形成共同理解</h2>
          <p>分析完成后将在此显示。</p>
          <button className="primary" onClick={() => setStarting(true)}>
            新建分析会话
          </button>
        </section>
      )}
      {showLegacyReport && detail && report && (
        <>
          <section className="panel risk-report-head">
            <div>
              <div className="row">
                <Badge tone="blue">本地导入</Badge>
                <Badge>{outcomes[report.outcome]}</Badge>
                <span className="hint">
                  报告 #{detail.id} · {time(detail.created_at)}
                </span>
              </div>
              <h2>{detail.title}</h2>
              <p className="hint">导入者：{detail.created_by}</p>
            </div>
            <div className="row">
              <button onClick={() => setHistory(true)}>分析记录</button>
              <Link className="action primary" to={`/requirements/chat/${detail.id}`}>
                需求分析对话
              </Link>
              <button disabled={busy} onClick={() => void exportJSON('input')}>
                导出输入
              </button>
              <button disabled={busy} onClick={() => void exportJSON('report')}>
                导出结果
              </button>
            </div>
          </section>
          <section className="risk-summary">
            <div>
              <span className="risk-eyebrow">总体结论 · 本次所选范围</span>
              <h2>
                {report.summary.assessment === 'NEEDS_CLARIFICATION'
                  ? '先澄清关键规则，再完善验收条件'
                  : report.summary.assessment === 'INSUFFICIENT_MATERIAL'
                    ? '资料不足，暂不能形成完整判断'
                    : '本次已检查范围未发现实质风险'}
              </h2>
              <p>{report.summary.conclusion}</p>
            </div>
            <div className="risk-metrics">
              {Object.entries(riskLevels).map(([key, label]) => (
                <button
                  className={`risk-metric ${key}`}
                  key={key}
                  onClick={() => {
                    setLevel(key);
                    setTab('risks');
                  }}
                >
                  <strong>{report.risks.filter((r) => r.severity === key).length}</strong>
                  <span>{label}风险</span>
                </button>
              ))}
              <div className="risk-metric">
                <strong>
                  {
                    report.risks.filter((r) =>
                      ['PENDING', 'NEEDS_INFO'].includes(status(detail, r.key)),
                    ).length
                  }
                </strong>
                <span>待处理</span>
              </div>
            </div>
          </section>
          <div className="tabs risk-tabs">
            {(
              [
                ['risks', '风险清单'],
                ['functions', '功能清单'],
                ['report', '完整报告'],
                ['sources', '输入与来源'],
              ] as const
            ).map(([key, title]) => (
              <button
                key={key}
                className={tab === key ? 'selected' : ''}
                onClick={() => setTab(key)}
              >
                {title}
                {key === 'risks'
                  ? ` · ${report.risks.length}`
                  : key === 'functions'
                    ? ` · ${report.functions.length}`
                    : ''}
              </button>
            ))}
          </div>
          {tab === 'risks' && (
            <div className="risk-workspace">
              <aside className="panel risk-functions">
                <div className="panel-head">
                  <h2>功能范围</h2>
                </div>
                <button
                  className={`risk-function ${!feature ? 'active' : ''}`}
                  onClick={() => setFeature('')}
                >
                  全部功能 <Badge>{report.risks.length}</Badge>
                </button>
                {report.functions.map((f) => (
                  <button
                    key={f.key}
                    className={`risk-function ${feature === f.key ? 'active' : ''}`}
                    onClick={() => setFeature(f.key)}
                  >
                    <span>
                      <small>{f.module || '模块未明确'}</small>
                      {f.name}
                    </span>
                    <Badge>{f.risk_keys.length}</Badge>
                  </button>
                ))}
              </aside>
              <section className="panel risk-list">
                <div className="panel-head">
                  <h2>
                    {report.functions.find((f) => f.key === feature)?.name || '全部功能'} · 风险清单
                  </h2>
                  <Badge>{rows.length} 项</Badge>
                </div>
                <div className="risk-filters">
                  <FormSelect
                    label="风险等级"
                    value={level}
                    onChange={setLevel}
                    options={[
                      { value: '', label: '全部等级' },
                      ...Object.entries(riskLevels).map(([value, label]) => ({
                        value,
                        label: `${label}风险`,
                      })),
                    ]}
                  />
                  <FormSelect
                    label="处理状态"
                    value={state}
                    onChange={setState}
                    options={[
                      { value: '', label: '全部状态' },
                      ...Object.entries(riskStates).map(([value, label]) => ({ value, label })),
                    ]}
                  />
                </div>
                {rows.map((r) => (
                  <article className="risk-card" key={r.key}>
                    <div className="row">
                      <Badge tone={r.severity}>{riskLevels[r.severity]}</Badge>
                      <Badge>{riskTypes[r.type]}</Badge>
                      <span className="hint">{r.key}</span>
                      <span className="risk-card-status">
                        <Badge>{riskStates[status(detail, r.key)]}</Badge>
                      </span>
                    </div>
                    <h3>
                      <button className="risk-title" onClick={() => setRiskKey(r.key)}>
                        {r.title}
                      </button>
                    </h3>
                    <p>{r.description}</p>
                    <div className="risk-impact">
                      <strong>可能影响</strong>
                      <span>{r.impact}</span>
                    </div>
                    <div className="between">
                      <span className="hint">
                        {r.evidence.length} 处固定依据
                        {report.summary.priority_risk_keys.includes(r.key) ? ' · 优先处理' : ''}
                      </span>
                      <button className="link" onClick={() => setRiskKey(r.key)}>
                        查看依据与处理 →
                      </button>
                    </div>
                  </article>
                ))}
                {!rows.length && (
                  <div className="risk-empty">
                    <h3>当前范围没有风险项</h3>

                    <button
                      onClick={() => {
                        setLevel('');
                        setState('');
                        setFeature('');
                      }}
                    >
                      清空筛选
                    </button>
                  </div>
                )}
                <details className="risk-suggestions">
                  <summary>
                    可选优化建议 · {report.optional_suggestions.length} 项 · 不计风险
                  </summary>
                  {report.optional_suggestions.map((s) => (
                    <div key={s.key}>
                      <h4>{s.title}</h4>
                      <p>{s.proposal}</p>
                      <p className="hint">
                        理由：{s.rationale}
                        <br />
                        取舍：{s.tradeoffs}
                      </p>
                    </div>
                  ))}
                </details>
              </section>
            </div>
          )}
          {tab === 'functions' && (
            <section className="panel panel-pad">
              <h2>已识别功能 · {report.functions.length}</h2>
              {report.functions.map((f) => (
                <article className="risk-card" key={f.key}>
                  <p className="hint">
                    {f.key} · {f.module || '模块未明确'}
                  </p>
                  <h3>{f.name}</h3>
                  <p>{f.scope}</p>
                  <div className="row">
                    <Badge>{f.risk_keys.length} 项风险</Badge>
                    <button
                      className="link"
                      onClick={() => {
                        setFeature(f.key);
                        setLevel('');
                        setState('');
                        setTab('risks');
                      }}
                    >
                      查看对应风险
                    </button>
                  </div>
                  <details className="mt">
                    <summary>功能依据</summary>
                    <EvidenceList evidence={f.evidence} detail={detail} onSource={openSource} />
                  </details>
                </article>
              ))}
              {!report.functions.length && <p>本次未识别可确认的功能，详见报告边界。</p>}
            </section>
          )}
          {tab === 'report' && (
            <FullReport detail={detail} onRisk={setRiskKey} onSource={openSource} />
          )}
          {tab === 'sources' && (
            <section className="panel panel-pad">
              <h2>输入与固定来源</h2>
              <p className="doc-note">摘录已匹配导入文本，关联原件仍需人工核对。</p>
              <p>本次关注点：{detail.input.focus || '未设置'}</p>
              <p className="hint">调用标识：{detail.input.request_id}</p>
              {detail.input.materials.map((m) => {
                const b = detail.bindings.find((b) => b.source_id === m.source_id);
                return (
                  <article className="evidence" key={m.source_id}>
                    <h3>{m.name}</h3>
                    <p>
                      {m.source_id} · {m.origin === 'PROTOTYPE' ? '原型资料' : '需求资料'} ·{' '}
                      {m.segments.length} 个输入片段
                    </p>
                    <p className="hint">
                      输入读取状态：{m.read_state} {m.read_note}
                      <br />
                      输入快照：{m.snapshot_ref || '未取得内容'}
                    </p>
                    <p>
                      系统关联：{b?.name || '未关联'}{' '}
                      {b?.version ? `· v${b.version.number}` : '· 实时来源元数据'}
                      {b?.deleted ? ' · 资料已删除，历史保留' : ''}
                    </p>
                    <button className="small" onClick={() => openSource(m.source_id)}>
                      查看输入原文与资料
                    </button>
                  </article>
                );
              })}
            </section>
          )}
        </>
      )}
      {history && (
        <CaseDialog title="分析记录" busy={false} onClose={() => setHistory(false)} wide>
          {items.map((item) => (
            <div className="evidence" key={item.id}>
              <div className="between">
                <h3>{item.title}</h3>
                <Badge>{outcomes[item.outcome]}</Badge>
              </div>
              <p className="hint">
                {time(item.created_at)} · {item.created_by} · {item.functions} 个功能 · {item.risks}{' '}
                项风险
              </p>
              <button
                className="link"
                onClick={() => {
                  setSelected(item.id);
                  setHistory(false);
                  setTab('risks');
                }}
              >
                打开报告
              </button>
            </div>
          ))}
          <div className="row mt">
            <button disabled={loading || page === 1} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            <span>第 {page} 页</span>
            <button disabled={loading || !more} onClick={() => setPage((p) => p + 1)}>
              下一页
            </button>
            <PageJump page={page} onChange={setPage} disabled={loading} />
          </div>
        </CaseDialog>
      )}
      {scopeOpen && detailLoading && (
        <CaseDialog title="分析范围与边界" busy={false} onClose={() => setScopeOpen(false)}>
          <p role="status">正在加载分析记录…</p>
        </CaseDialog>
      )}
      {scopeOpen && detail && !detailLoading && (
        <ScopeDialog detail={detail} onClose={() => setScopeOpen(false)} />
      )}
      {importing && (
        <ImportReport
          base={base}
          project={project.id}
          onSessionEnd={onSessionEnd}
          onClose={() => setImporting(false)}
          onImported={(v) => {
            setImporting(false);
            setDetail(v);
            setSelected(v.id);
            setPage(1);
            setNotice(
              v.duplicate
                ? '相同输入与结果已存在，已打开原报告，处理记录保留。'
                : '报告已入库，功能、风险及来源可直接查看。',
            );
            setReload((n) => n + 1);
          }}
        />
      )}
      {starting && (
        <StartAnalysis
          project={project.id}
          base={base}
          retry={starting === true ? null : starting}
          onClose={() => setStarting(null)}
          onStarted={() => {
            setStarting(null);
            setReload((value) => value + 1);
            setNotice('分析请求已保存，后台会继续处理。');
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
      {catalogRisk && (
        <CatalogRiskDialog
          item={catalogRisk}
          base={base}
          projectId={project.id}
          onClose={() => setCatalogRisk(null)}
          onSaved={() => {
            setCatalogRisk(null);
            setReload((value) => value + 1);
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
      {risk && detail && (
        <HandleRisk
          key={`${detail.id}:${risk.key}`}
          base={base}
          detail={detail}
          risk={risk}
          onClose={() => setRiskKey(null)}
          onSource={openSource}
          onSessionEnd={onSessionEnd}
          onSaved={(v) => {
            setDetail(v);
            setRiskKey(null);
            setNotice('风险处理已保存。');
          }}
        />
      )}
      {sourceKey && detail && (
        <SourceDialog
          detail={detail}
          sourceId={sourceKey}
          onClose={() => setSourceKey(null)}
          onSessionEnd={onSessionEnd}
        />
      )}
    </div>
  );
}

function FullReport({
  detail,
  onRisk,
  onSource,
}: {
  detail: RiskDetail;
  onRisk: (key: string) => void;
  onSource: (key: string) => void;
}) {
  const r = detail.report;
  return (
    <section className="panel panel-pad risk-full-report">
      <h2>{detail.title}</h2>
      <p>{r.summary.conclusion}</p>
      <h3>优先处理</h3>
      {r.summary.priority_risk_keys.map((key) => (
        <p key={key}>
          <button className="link" onClick={() => onRisk(key)}>
            {r.risks.find((r) => r.key === key)?.title || key}
          </button>
        </p>
      ))}
      {!r.summary.priority_risk_keys.length && <p className="hint">未单列优先事项。</p>}
      <details className="evidence">
        <summary>功能范围 · {r.functions.length} 个功能</summary>
        {r.functions.map((f) => (
          <div key={f.key}>
            <h4>
              {f.module || '模块未明确'} / {f.name}
            </h4>
            <p>{f.scope}</p>
            <p className="hint">关联风险：{f.risk_keys.join('、') || '本次未发现风险'}</p>
          </div>
        ))}
      </details>
      <h3>风险与完善建议</h3>
      {r.risks.map((risk) => (
        <article className="risk-card" key={risk.key}>
          <h3>
            <button className="risk-title" onClick={() => onRisk(risk.key)}>
              {risk.key} · {risk.title}
            </button>
          </h3>
          <p>{risk.description}</p>
          <p>
            等级：{riskLevels[risk.severity]} · {risk.severity_reason}
          </p>
          <p>影响：{risk.impact}</p>
          <p>待确认：{risk.questions.join('；')}</p>
          <p>建议：{risk.improvement.proposal}</p>
          <p>理由：{risk.improvement.rationale}</p>
          <p>取舍：{risk.improvement.tradeoffs}</p>
          <p>
            处理状态：{riskStates[status(detail, risk.key)]}
            <br />
            人工结论：{detail.handling.find((h) => h.risk_key === risk.key)?.note || '尚未填写'}
          </p>
          <EvidenceList evidence={risk.evidence} detail={detail} onSource={onSource} />
          {risk.source_comparison && (
            <div className="evidence">
              <h4>来源对比</h4>
              {risk.source_comparison.sides.map((side, i) => (
                <div key={i}>
                  <p>{side.statement}</p>
                  <EvidenceList evidence={side.evidence} detail={detail} onSource={onSource} />
                </div>
              ))}
              <p>已知：{risk.source_comparison.known_facts}</p>
              <p>未知：{risk.source_comparison.unknowns}</p>
            </div>
          )}
        </article>
      ))}
      <h3>可选优化 · 不计风险</h3>
      {r.optional_suggestions.map((s) => (
        <div className="evidence" key={s.key}>
          <h4>{s.title}</h4>
          <p>{s.proposal}</p>
          <p>
            理由：{s.rationale}
            <br />
            取舍：{s.tradeoffs}
          </p>
        </div>
      ))}
      <h3>覆盖情况</h3>
      {r.coverage.map((c) => (
        <details className="evidence" key={c.source_id}>
          <summary>
            {detail.input.materials.find((m) => m.source_id === c.source_id)?.name || c.source_id} ·{' '}
            {c.segments.length} 个片段
          </summary>
          {c.segments.map((s) => (
            <p key={s.segment_id}>
              <strong>
                {s.segment_id} ·{' '}
                {s.disposition === 'REVIEWED'
                  ? '已审查'
                  : s.disposition === 'NOT_RELEVANT'
                    ? '范围外'
                    : '未处理'}
              </strong>
              <br />
              {s.reason}
              <br />
              <span className="hint">
                功能：{s.function_keys.join('、') || '无'} · 风险：{s.risk_keys.join('、') || '无'}
              </span>
            </p>
          ))}
          {c.limitation && <p>{c.limitation}</p>}
        </details>
      ))}
      <h3>分析边界</h3>
      {r.limitations.map((l, i) => (
        <div className="evidence" key={i}>
          <p>{l.detail}</p>
          <p className="hint">影响：{l.effect}</p>
        </div>
      ))}
      {!r.limitations.length && <p>未单列限制，仅代表本次所选范围。</p>}
    </section>
  );
}

function SourceDialog({
  detail,
  sourceId,
  onClose,
  onSessionEnd,
}: {
  detail: RiskDetail;
  sourceId: string;
  onClose: () => void;
  onSessionEnd: () => void;
}) {
  const material = detail.input.materials.find((m) => m.source_id === sourceId),
    binding = detail.bindings.find((b) => b.source_id === sourceId);
  return (
    <CaseDialog title={material?.name || '来源对照'} busy={false} onClose={onClose} wide>
      <p className="doc-note">请核对关联资料与本次分析输入是否对应。</p>
      {binding && (
        <details className="evidence">
          <summary>
            关联资料：{binding.name}{' '}
            {binding.version ? `v${binding.version.number}` : '（实时来源记录）'}
            {binding.deleted ? ' · 已删除' : ''}
          </summary>
          {binding.version ? (
            <>
              <p className="hint">SHA256：{binding.version.sha256}</p>
              <a
                className="action small"
                href={`/api/projects/${detail.project_id}/documents/versions/${binding.version.id}/file`}
              >
                下载原件
              </a>
              <OriginalPreview
                base={`/api/projects/${detail.project_id}/documents`}
                version={binding.version}
                readOnly
                onOpen={() => {}}
                onLinksChanged={() => {}}
                onSessionEnd={onSessionEnd}
              />
            </>
          ) : (
            <p className="hint">
              {binding.url || binding.branch || '未提供地址'} <br /> 关联时记录提交：
              {binding.commit || '无'}
            </p>
          )}
        </details>
      )}
      {material?.segments.map((s) => (
        <details className="evidence" key={s.segment_id}>
          <summary>
            {s.segment_id} · {s.location}
          </summary>
          {s.text && <pre className="risk-input-text">{s.text}</pre>}
          {s.image_ref && (
            <p className="hint">输入附件引用：{s.image_ref}；请展开上方关联原件核对。</p>
          )}
        </details>
      ))}
      {!material?.segments.length && <p>{material?.read_note || '没有可读取片段。'}</p>}
    </CaseDialog>
  );
}

function ScopeDialog({ detail, onClose }: { detail: RiskDetail; onClose: () => void }) {
  return (
    <CaseDialog title="分析范围与边界" busy={false} onClose={onClose} wide>
      <div className="row">
        <Badge>报告 #{detail.id}</Badge>
        <Badge>{outcomes[detail.report.outcome]}</Badge>
      </div>
      {detail.review_warnings.length > 0 && (
        <details className="notice mt" open>
          <summary>{detail.review_warnings.length} 处 AI 依据/覆盖待人工核对</summary>
          <ul>
            {detail.review_warnings.map((warning, index) => (
              <li key={`${warning.path}-${index}`}>{warningText(warning)}</li>
            ))}
          </ul>
        </details>
      )}
      <h3 className="mt">固定资料 · {detail.input.materials.length} 份</h3>
      {detail.input.materials.map((material) => {
        const binding = detail.bindings.find((item) => item.source_id === material.source_id);
        return (
          <div className="evidence" key={material.source_id}>
            <strong>
              {material.name} · {binding?.version ? `v${binding.version.number}` : '当次快照'}
            </strong>
            <p>{material.segments.map((segment) => segment.location).join('；') || '所选资料'}</p>
            <p className="hint">
              {material.read_state} {material.read_note}
              {binding?.commit ? ` · 提交 ${binding.commit}` : ''}
            </p>
          </div>
        );
      })}
      <h3 className="mt">本次分析结论</h3>
      <p>{detail.report.summary.conclusion}</p>
      <h3 className="mt">本次关注点</h3>
      <p>{detail.input.focus || '未设置额外关注点'}</p>
      <h3 className="mt">分析边界</h3>
      {detail.report.limitations.length ? (
        <ul>
          {detail.report.limitations.map((item, index) => (
            <li key={index}>
              {item.detail}；影响：{item.effect}
            </li>
          ))}
        </ul>
      ) : (
        <p>本次输入未记录额外读取限制。</p>
      )}
      <details className="evidence mt">
        <summary>分析过程与诊断</summary>
        <p>发起人：{detail.created_by}</p>
        <p>
          资料：{detail.input.materials.length} 份 · 状态：{outcomes[detail.report.outcome]}
        </p>
      </details>
      <div className="row prototype-editor-footer">
        <button type="button" onClick={onClose}>
          关闭
        </button>
      </div>
    </CaseDialog>
  );
}

export function HandleRisk({
  base,
  detail,
  risk,
  onClose,
  onSource,
  onSessionEnd,
  onSaved,
}: {
  base: string;
  detail: RiskDetail;
  risk: Risk;
  onClose: () => void;
  onSource: (key: string) => void;
  onSessionEnd: () => void;
  onSaved: (v: RiskDetail) => void;
}) {
  const current = detail.handling.find((h) => h.risk_key === risk.key),
    [state, setState] = useState<RiskState>(current?.status || 'PENDING'),
    [note, setNote] = useState(current?.note || ''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const pending = useRef(false),
    controller = useRef(new AbortController());
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  return (
    <CaseDialog
      title={`${risk.key} · 风险详情`}
      busy={busy}
      onClose={onClose}
      className="prototype-editor-dialog"
      wide
    >
      <Form
        className="prototype-editor-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (pending.current) return;
          pending.current = true;
          setBusy(true);
          setError('');
          try {
            const v = await riskDetailRequest(`${base}/${detail.id}/handling`, detail.project_id, {
              method: 'POST',
              signal: controller.current.signal,
              body: JSON.stringify({
                risk_key: risk.key,
                status: state,
                note: note.trim(),
                revision: detail.revision,
              }),
            });
            if (!controller.current.signal.aborted) onSaved(v);
          } catch (error) {
            if (!controller.current.signal.aborted) setError(riskError(error, onSessionEnd));
          } finally {
            pending.current = false;
            if (!controller.current.signal.aborted) setBusy(false);
          }
        }}
      >
        <div className="prototype-editor-content risk-detail-content">
          <div className="row">
            <Badge tone={risk.severity}>{riskLevels[risk.severity]}风险</Badge>
            <Badge>{riskTypes[risk.type]}</Badge>
          </div>
          <h2>{risk.title}</h2>
          <p>{risk.description}</p>
          <p className="hint">等级依据：{risk.severity_reason}</p>
          {risk.checked_scope.length > 0 && (
            <details className="evidence">
              <summary>缺口判断的检查范围</summary>
              {risk.checked_scope.map((scope) => (
                <p key={scope.source_id}>
                  {detail.input.materials.find((m) => m.source_id === scope.source_id)?.name ||
                    scope.source_id}
                  ：{scope.segment_ids.join('、')}
                </p>
              ))}
            </details>
          )}
          <section>
            <h3>原文依据</h3>
            <EvidenceList evidence={risk.evidence} detail={detail} onSource={onSource} />
          </section>
          <div className="risk-detail-grid">
            <section>
              <h3>可能影响</h3>
              <p>{risk.impact}</p>
            </section>
            <section>
              <h3>待确认事项</h3>
              <ul>
                {risk.questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          </div>
          <section>
            <h3>完善建议 · 需人工确认</h3>
            <p>{risk.improvement.proposal}</p>
            <p className="hint">
              理由：{risk.improvement.rationale}
              <br />
              取舍：{risk.improvement.tradeoffs}
            </p>
          </section>
          {risk.source_comparison && (
            <section>
              <h3>
                来源对比 ·{' '}
                {risk.source_comparison.relation === 'CONFLICT' ? '冲突待确认' : '表达差异'}
              </h3>
              {risk.source_comparison.sides.map((s, i) => (
                <div key={i}>
                  <p>{s.statement}</p>
                  <EvidenceList evidence={s.evidence} detail={detail} onSource={onSource} />
                </div>
              ))}
              <p>已知：{risk.source_comparison.known_facts}</p>
              <p>未知：{risk.source_comparison.unknowns}</p>
            </section>
          )}
          <section>
            <h3>人工处理</h3>

            <FormSelect
              label="处理状态"
              value={state}
              onChange={(v) => setState(v as RiskState)}
              disabled={busy}
              options={Object.entries(riskStates).map(([value, label]) => ({ value, label }))}
            />
            <label className="form-field mt">
              处理结论
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={3000}
                required={state !== 'PENDING'}
                disabled={busy}
                rows={3}
                placeholder="填写确认结论、补充资料位置或不适用原因"
              />
            </label>
          </section>
          <details className="evidence">
            <summary>处理记录 · {current?.history.length || 0} 条</summary>
            {current?.history
              .slice()
              .reverse()
              .map((h, i) => (
                <div key={i}>
                  <strong>
                    {riskStates[h.from]} → {riskStates[h.to]}
                  </strong>
                  <p className="hint">
                    {h.actor} · {time(h.time)}
                  </p>
                  <p>{h.note}</p>
                </div>
              ))}
          </details>
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
        </div>
        <div className="row prototype-editor-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="primary" disabled={busy}>
            {busy ? '保存中…' : '保存处理'}
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}

type Loaded = Awaited<ReturnType<typeof readRiskFile>>;
export function ImportReport({
  base,
  project,
  onClose,
  onImported,
  onSessionEnd,
}: {
  base: string;
  project: number;
  onClose: () => void;
  onImported: (v: RiskDetail) => void;
  onSessionEnd: () => void;
}) {
  const [input, setInput] = useState<(Loaded & { parsed: Input }) | null>(null),
    [report, setReport] = useState<(Loaded & { parsed: RiskReport }) | null>(null),
    [options, setOptions] = useState<MaterialOption[]>([]),
    [bindings, setBindings] = useState<SourceBinding[]>([]),
    [title, setTitle] = useState(''),
    [busy, setBusy] = useState(false),
    [reading, setReading] = useState({ input: false, report: false }),
    [error, setError] = useState(''),
    [sourcesError, setSourcesError] = useState(''),
    [reload, setReload] = useState(0);
  const controller = useRef(new AbortController()),
    pending = useRef(false),
    generations = useRef({ input: 0, report: 0 });
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  useEffect(() => {
    const c = new AbortController();
    setSourcesError('');
    riskOptions(`${base}/options`, c.signal)
      .then((v) => {
        if (!c.signal.aborted) setOptions(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) setSourcesError(riskError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [base, onSessionEnd, reload]);
  async function pick(kind: 'input' | 'report', files: File[]) {
    const file = files[0];
    if (!file || pending.current) return;
    const generation = ++generations.current[kind];
    setError('');
    setReading((old) => ({ ...old, [kind]: true }));
    if (kind === 'input') {
      setInput(null);
      setBindings([]);
    } else setReport(null);
    try {
      const loaded = await readRiskFile(file);
      if (controller.current.signal.aborted || generation !== generations.current[kind]) return;
      if (kind === 'input') setInput({ ...loaded, parsed: parseRiskInput(loaded.data) });
      else {
        setReport({ ...loaded, parsed: parseRiskReport(loaded.data) });
        setTitle((old) => old || file.name.replace(/\.json$/i, ''));
      }
    } catch (e) {
      if (!controller.current.signal.aborted && generation === generations.current[kind])
        setError(riskError(e, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted && generation === generations.current[kind])
        setReading((old) => ({ ...old, [kind]: false }));
    }
  }
  const matched = !!input && !!report && input.parsed.request_id === report.parsed.request_id;
  return (
    <CaseDialog
      title="导入本地分析结果"
      busy={busy}
      onClose={onClose}
      className="prototype-editor-dialog"
      wide
    >
      <Form
        className="prototype-editor-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (pending.current || !input || !report) return;
          if (!matched) {
            setError('两份文件的 request_id 不一致，请选择同一次分析的输入与结果。');
            return;
          }
          if (
            input.parsed.materials.some((m) => {
              const b = bindings.find((b) => b.source_id === m.source_id),
                option = options.find((o) => o.id === b?.document_id);
              return !option || (['FILE', 'DIRECTORY'].includes(option.kind) && !b?.version_id);
            })
          ) {
            setError('请为每份来源关联当前项目资料；文件资料需明确选择固定版本。');
            return;
          }
          pending.current = true;
          setBusy(true);
          setError('');
          try {
            const v = await riskDetailRequest(`${base}/import`, project, {
              method: 'POST',
              signal: controller.current.signal,
              body: JSON.stringify({
                title: title.trim(),
                input_filename: input.filename,
                report_filename: report.filename,
                input_json: input.text,
                report_json: report.text,
                bindings,
              }),
            });
            if (!controller.current.signal.aborted) onImported(v);
          } catch (e) {
            if (!controller.current.signal.aborted) setError(riskError(e, onSessionEnd));
          } finally {
            pending.current = false;
            if (!controller.current.signal.aborted) setBusy(false);
          }
        }}
      >
        <div className="prototype-editor-content">
          <p className="doc-note">
            选择 input.json 与结果 JSON（report.json 或 risk-report.json），每份最大16MB。
          </p>
          <div className="risk-import-files">
            {(['input', 'report'] as const).map((kind) => (
              <section className="evidence" key={kind}>
                <h3>{kind === 'input' ? '分析输入 · input.json' : '分析结果 · report.json'}</h3>
                <FilePicker
                  accept=".json"
                  disabled={busy}
                  onChange={(files) => void pick(kind, files)}
                />
                <p className="hint">
                  {reading[kind]
                    ? '读取中…'
                    : (kind === 'input' ? input?.filename : report?.filename) || '尚未选择'}
                </p>
              </section>
            ))}
          </div>
          <label className="form-field">
            报告名称
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={200}
              disabled={busy}
            />
          </label>
          {report && (
            <div className="evidence">
              <strong>
                待校验：{report.parsed.functions.length} 个功能 · {report.parsed.risks.length}{' '}
                项风险
              </strong>
              <p>{report.parsed.summary.conclusion}</p>
            </div>
          )}
          {input && report && !matched && <p className="form-error">两份文件的调用标识不一致。</p>}
          {input && (
            <section>
              <h3>关联系统已有资料</h3>
              <p className="hint">选择项目中已有原件，无需重复上传。</p>
              {input.parsed.materials.map((m) => {
                const b = bindings.find((b) => b.source_id === m.source_id),
                  option = options.find((o) => o.id === b?.document_id);
                return (
                  <div className="evidence" key={m.source_id}>
                    <strong>
                      {m.source_id} · {m.name}
                    </strong>
                    <p className="hint">
                      {m.origin === 'PROTOTYPE' ? '原型资料' : '需求资料'} · {m.segments.length}{' '}
                      个片段 · {m.read_state}
                    </p>
                    <FormSelect
                      label="系统资料"
                      value={String(b?.document_id || '')}
                      disabled={busy}
                      required
                      onChange={(id) =>
                        setBindings((old) => [
                          ...old.filter((b) => b.source_id !== m.source_id),
                          ...(id
                            ? [
                                {
                                  source_id: m.source_id,
                                  document_id: Number(id),
                                  version_id: null,
                                },
                              ]
                            : []),
                        ])
                      }
                      options={[
                        { value: '', label: '请选择对应资料，不按文件名自动匹配' },
                        ...options
                          .filter((o) => o.purpose === m.origin)
                          .map((o) => ({
                            value: String(o.id),
                            label: `${o.name} · ${o.kind === 'FILE' ? '文件' : o.kind === 'GITHUB' ? 'GitHub' : '链接'}`,
                          })),
                      ]}
                    />
                    {option && ['FILE', 'DIRECTORY'].includes(option.kind) && (
                      <FormSelect
                        label="固定文件版本"
                        value={String(b?.version_id || '')}
                        disabled={busy}
                        required
                        onChange={(v) =>
                          setBindings((old) =>
                            old.map((b) =>
                              b.source_id === m.source_id
                                ? { ...b, version_id: v ? Number(v) : null }
                                : b,
                            ),
                          )
                        }
                        options={[
                          { value: '', label: '请选择实际用于本次分析的版本' },
                          ...option.versions.map((v) => ({
                            value: String(v.id),
                            label: `v${v.number} · ${v.filename} · ${time(v.created_at)}`,
                          })),
                        ]}
                      />
                    )}
                  </div>
                );
              })}
            </section>
          )}
          {sourcesError && (
            <p className="form-error" role="alert">
              {sourcesError}
              <button type="button" disabled={busy} onClick={() => setReload((n) => n + 1)}>
                重新加载资料
              </button>
            </p>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="row prototype-editor-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button
            className="primary"
            disabled={busy || reading.input || reading.report || !matched || !!sourcesError}
          >
            {busy ? '校验并保存中…' : '校验并入库'}
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}

function StartAnalysis({
  project,
  base,
  retry,
  onClose,
  onStarted,
  onSessionEnd,
}: {
  project: number;
  base: string;
  retry: RiskAnalysisTask | null;
  onClose: () => void;
  onStarted: () => void;
  onSessionEnd: () => void;
}) {
  const [options, setOptions] = useState<MaterialOption[]>([]);
  const [selected, setSelected] = useState<Record<number, number | null>>(
    Object.fromEntries(
      (retry?.selections || []).map((item) => [item.document_id, item.version_id]),
    ),
  );
  const [linkPages, setLinkPages] = useState<Record<number, LinkSelection>>(
    Object.fromEntries(
      (retry?.selections || [])
        .filter((s) => s.paths.length)
        .map((s) => [s.document_id, { paths: s.paths, snapshot: s.snapshot }]),
    ),
  );
  const [title, setTitle] = useState(retry ? `${retry.title} · 重新分析` : '');
  const [focus, setFocus] = useState(retry?.focus || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [ai, setAi] = useState('正在读取个人AI配置…');
  const [aiSelection, setAISelection] = useState<AISelection | null>(null);
  useEffect(() => {
    const c = new AbortController();
    riskOptions(`${base}/options`, c.signal)
      .then((value) => {
        if (!c.signal.aborted) setOptions(value);
      })
      .catch((reason) => {
        if (!c.signal.aborted) setError(riskError(reason, onSessionEnd));
      });
    readSelectedAI(c.signal)
      .then((value) => {
        if (!c.signal.aborted) setAISelection(value.personal);
        if (!c.signal.aborted)
          setAi(
            value.personal
              ? `${callModeName(value.personal.call_mode)} · ${value.personal.name} · ${value.personal.model}`
              : '个人配置未设置',
          );
      })
      .catch((reason) => {
        if (!c.signal.aborted) setError(riskError(reason, onSessionEnd));
      });
    return () => c.abort();
  }, [base, onSessionEnd]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selections =
      retry?.selections ||
      Object.entries(selected).map(([document_id, version_id]) => {
        const id = Number(document_id);
        return {
          document_id: id,
          version_id,
          ...(options.find((o) => o.id === id)?.kind === 'LINK' ||
          options.find((o) => o.id === id)?.kind === 'DIRECTORY'
            ? {
                paths: linkPages[id]?.paths || [],
                snapshot: linkPages[id]?.snapshot || '',
                url:
                  options.find((o) => o.id === id)?.kind === 'LINK'
                    ? options.find((o) => o.id === id)?.url || null
                    : null,
              }
            : {}),
        };
      });
    if (!selections.length) {
      setError('需求资料或原型资料至少选择一项。');
      return;
    }
    if (
      !retry &&
      selections.some(
        (s) =>
          ['LINK', 'DIRECTORY'].includes(options.find((o) => o.id === s.document_id)?.kind || '') &&
          !('paths' in s && s.paths?.length),
      )
    ) {
      setError('请先读取原型链接并选择具体页面。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await apiRequest(`/api/projects/${project}/requirements/risk-analyses`, {
        method: 'POST',
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          title,
          focus,
          selections,
          retry_of: retry?.id || null,
          ai_version: aiSelection?.version,
          ai_call_mode: aiSelection?.call_mode,
          ai_preference_version: aiSelection?.preference_version,
        }),
      });
      onStarted();
    } catch (reason) {
      setError(riskError(reason, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  function materialRow(item: MaterialOption) {
    const checked = Object.hasOwn(selected, item.id);
    return (
      <div className="risk-material-row" key={item.id}>
        <label className="risk-source-check">
          <input
            type="checkbox"
            checked={checked}
            disabled={busy || (['FILE', 'DIRECTORY'].includes(item.kind) && !item.versions.length)}
            onChange={(event) =>
              setSelected((current) => {
                const next = { ...current };
                if (event.target.checked)
                  next[item.id] = ['FILE', 'DIRECTORY'].includes(item.kind)
                    ? item.versions[0]?.id || null
                    : null;
                else delete next[item.id];
                return next;
              })
            }
          />{' '}
          <span>
            <strong>
              {item.kind === 'FILE'
                ? item.versions.find((v) => v.id === selected[item.id])?.filename ||
                  item.versions[0]?.filename ||
                  item.name
                : item.name}
            </strong>
            <small className="hint">
              {['FILE', 'DIRECTORY'].includes(item.kind)
                ? '固定版本文件'
                : item.kind === 'LINK'
                  ? '原型链接 · 选择页面后读取正文'
                  : 'GitHub · 固定提交与已选文件'}
            </small>
          </span>
        </label>
        {checked && ['FILE', 'DIRECTORY'].includes(item.kind) && (
          <FormSelect
            label="固定版本"
            value={String(selected[item.id] || '')}
            onChange={(value) => {
              setSelected((current) => ({ ...current, [item.id]: Number(value) }));
              if (item.kind === 'DIRECTORY')
                setLinkPages((current) => ({ ...current, [item.id]: { paths: [], snapshot: '' } }));
            }}
            disabled={busy}
            options={item.versions.map((version) => ({
              value: String(version.id),
              label: `v${version.number} · ${version.filename}`,
            }))}
          />
        )}
        {checked && item.kind === 'DIRECTORY' && selected[item.id] && !retry && (
          <PrototypeDirectoryFiles
            key={`${item.id}:${selected[item.id]}`}
            projectId={project}
            documentId={item.id}
            versionId={selected[item.id]!}
            value={linkPages[item.id]?.paths || []}
            onChange={(paths) =>
              setLinkPages((current) => ({ ...current, [item.id]: { paths, snapshot: '' } }))
            }
            onSessionEnd={onSessionEnd}
            disabled={busy}
          />
        )}
        {checked && item.kind === 'LINK' && !retry && (
          <PrototypeLinkPages
            projectId={project}
            documentId={item.id}
            value={linkPages[item.id] || { paths: [], snapshot: '' }}
            onChange={(value) => setLinkPages((current) => ({ ...current, [item.id]: value }))}
            onSessionEnd={onSessionEnd}
            disabled={busy}
          />
        )}
        {checked && !['FILE', 'DIRECTORY'].includes(item.kind) && (
          <p className="hint">
            {item.kind === 'LINK'
              ? retry
                ? '沿用原报告的所选页面范围。'
                : '只读取所选页面的 HTML 和原型说明，不执行脚本。'
              : '使用已固定提交和已选文件。'}
          </p>
        )}
      </div>
    );
  }
  return (
    <CaseDialog
      title={retry ? '重试分析会话' : '新建分析会话'}
      busy={busy}
      onClose={onClose}
      wide
      className="prototype-editor-dialog risk-analysis-dialog requirement-ui"
    >
      <Form className="prototype-editor-form" onSubmit={(event) => void submit(event)}>
        <div className="prototype-editor-content">
          <label className="field-label">
            会话名称
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              maxLength={200}
              disabled={busy}
            />
          </label>

          {retry ? (
            <section className="evidence">
              <strong>沿用原报告的所选资料快照</strong>
              <p>{retry.selections.length} 份固定资料</p>
              <p className="hint">重试将创建新报告；修改资料范围请新建分析。</p>
            </section>
          ) : (
            <div className="risk-source-picker">
              <p className="hint">至少选择一份需求或原型资料。</p>
              {(['REQUIREMENT', 'PROTOTYPE'] as const).map((purpose) => (
                <fieldset className="risk-source-group" key={purpose}>
                  <legend>
                    {purpose === 'REQUIREMENT' ? '需求资料（可选）' : '原型资料（可选）'}
                  </legend>
                  {purpose === 'REQUIREMENT' ? (
                    options
                      .filter((item) => item.purpose === purpose)
                      .map((item) => (
                        <div className="evidence" key={item.id}>
                          {materialRow(item)}
                        </div>
                      ))
                  ) : (
                    <>
                      {options.some(
                        (item) =>
                          item.purpose === purpose && ['FILE', 'DIRECTORY'].includes(item.kind),
                      ) && (
                        <div className="evidence">
                          {options
                            .filter(
                              (item) =>
                                item.purpose === purpose &&
                                ['FILE', 'DIRECTORY'].includes(item.kind),
                            )
                            .map(materialRow)}
                        </div>
                      )}
                      <h4 className="mt">原型链接</h4>
                      {options
                        .filter((item) => item.purpose === purpose && item.kind === 'LINK')
                        .map((item) => (
                          <div className="evidence" key={item.id}>
                            {materialRow(item)}
                          </div>
                        ))}
                      {!options.some(
                        (item) => item.purpose === purpose && item.kind === 'LINK',
                      ) && <p className="hint">暂无原型链接。</p>}
                      <h3 className="mt">GitHub HTML · 已选文件</h3>
                      <p className="hint">沿用原型资料中已核实的提交和文件范围。</p>
                      {options
                        .filter((item) => item.purpose === purpose && item.kind === 'GITHUB')
                        .map((item) => (
                          <div className="evidence" key={item.id}>
                            {materialRow(item)}
                          </div>
                        ))}
                      {!options.some(
                        (item) => item.purpose === purpose && item.kind === 'GITHUB',
                      ) && <p className="hint">暂无GitHub原型资料。</p>}
                    </>
                  )}
                  {!options.some((item) => item.purpose === purpose) && (
                    <p className="hint">暂无{purpose === 'REQUIREMENT' ? '需求' : '原型'}资料。</p>
                  )}
                </fieldset>
              ))}
            </div>
          )}
          <label className="field-label">
            分析目标
            <textarea
              value={focus}
              onChange={(event) => setFocus(event.target.value)}
              maxLength={3000}
              rows={3}
              disabled={busy}
              placeholder="不填写时审查全部所选资料"
            />
          </label>
          <details className="risk-analysis-service">
            <summary>本次使用：{ai}</summary>

            <p>后台执行，可离开页面。</p>
          </details>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="row prototype-editor-footer">
          <button type="button" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="primary" disabled={busy || (!retry && !options.length)}>
            {busy ? '正在保存…' : '开始分析'}
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}

function CatalogRiskDialog({
  item,
  base,
  projectId,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  item: CatalogItem;
  base: string;
  projectId: number;
  onClose: () => void;
  onSaved: () => void;
  onSessionEnd: () => void;
}) {
  const [state, setState] = useState<RiskState>(item.status);
  const [note, setNote] = useState(item.note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [warningDetail, setWarningDetail] = useState<RiskDetail | null>(null);
  const [warningError, setWarningError] = useState('');
  const coverageWarnings = item.review_warnings.filter(
    (warning) => warning.code === 'invalid_coverage' && warning.segment_id,
  );
  useEffect(() => {
    if (!coverageWarnings.length) return;
    const controller = new AbortController();
    riskDetailRequest(`${base}/${item.report_id}`, projectId, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setWarningDetail(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setWarningError(riskError(reason, onSessionEnd));
      });
    return () => controller.abort();
  }, [base, item.report_id, projectId, onSessionEnd, coverageWarnings.length]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const url =
      item.source_kind === 'MANUAL'
        ? `${base}/${item.report_id}/manual-risks/${item.manual_id}/handling`
        : `${base}/${item.report_id}/handling`;
    try {
      await apiRequest(url, {
        method: 'POST',
        body: JSON.stringify(
          item.source_kind === 'MANUAL'
            ? { status: state, note, revision: item.revision }
            : { risk_key: item.risk_key, status: state, note, revision: item.revision },
        ),
      });
      onSaved();
    } catch (reason) {
      setError(riskError(reason, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  const functionKey = item.functions[0]?.key || '';
  return (
    <CaseDialog
      title={`${item.risk_key} · 风险详情`}
      busy={busy}
      onClose={onClose}
      wide
      className="prototype-editor-dialog"
    >
      <Form className="prototype-editor-form" onSubmit={(event) => void submit(event)}>
        <div className="prototype-editor-content risk-detail-content">
          <div className="row">
            <Badge tone={item.risk.severity}>{riskLevels[item.risk.severity]}</Badge>
            <Badge>{riskTypes[item.risk.type]}</Badge>
            <Badge>{riskStates[item.status]}</Badge>
            <Badge>{item.functions.map((value) => value.name).join('、')}</Badge>
            <Badge>{item.source_kind === 'MANUAL' ? '人工新增' : 'AI分析'}</Badge>
          </div>
          <h2>{item.risk.title}</h2>
          <p>{item.risk.description}</p>
          {item.review_warnings.length > 0 && (
            <section className="notice" role="note">
              {coverageWarnings.length > 0 && (
                <p>
                  <strong>
                    {item.risk_key} 在 {coverageWarnings.length}{' '}
                    个资料片段上的功能归属与本风险不一致，需人工核对。
                  </strong>
                </p>
              )}
              {item.review_warnings.length > coverageWarnings.length && (
                <p>另有 {item.review_warnings.length - coverageWarnings.length} 处依据待核对。</p>
              )}
              {coverageWarnings.length > 0 && (
                <details>
                  <summary>查看片段与功能归属</summary>
                  {warningError && <p role="alert">无法读取片段对照：{warningError}</p>}
                  {!warningDetail && !warningError && <p role="status">正在读取片段对照…</p>}
                  {warningDetail?.id === item.report_id && (
                    <ul>
                      {coverageWarnings.map((warning, index) => {
                        const source = warningDetail.input.materials.find(
                          (material) => material.source_id === warning.source_id,
                        );
                        const segment = source?.segments.find(
                          (value) => value.segment_id === warning.segment_id,
                        );
                        const covered = warningDetail.report.coverage
                          .find((value) => value.source_id === warning.source_id)
                          ?.segments.find((value) => value.segment_id === warning.segment_id);
                        const names = covered?.function_keys.map(
                          (key) =>
                            warningDetail.report.functions.find((value) => value.key === key)
                              ?.name || key,
                        );
                        return (
                          <li key={`${warning.path}-${index}`}>
                            {source?.name || warning.source_id} ·{' '}
                            {segment?.location || warning.segment_id}： 片段标注“
                            {names?.join('、') || '无'}”；{item.risk_key} 归属“
                            {item.functions.map((value) => value.name).join('、')}”。
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </details>
              )}
              {item.review_warnings.length > coverageWarnings.length && (
                <ul>
                  {item.review_warnings
                    .filter((warning) => !coverageWarnings.includes(warning))
                    .map((warning, index) => (
                      <li key={`${warning.path}-${index}`}>{warningText(warning)}</li>
                    ))}
                </ul>
              )}
            </section>
          )}
          <section className="risk-detail-section">
            <h3>
              原文依据 <span className="hint">· 当次固定版本</span>
            </h3>
            {item.risk.evidence.map((evidence, index) => (
              <div className="evidence" key={index}>
                <strong>
                  {evidence.source_id} · {evidence.location}
                </strong>
                {evidence.excerpt && <blockquote>{evidence.excerpt}</blockquote>}
                {item.review_warnings.some(
                  (warning) =>
                    warning.code === 'evidence_excerpt_mismatch' &&
                    warning.source_id === evidence.source_id &&
                    warning.segment_id === evidence.segment_id,
                ) && <p className="form-error">摘录未与固定原文匹配，请人工核对。</p>}
                {evidence.observation && <p>{evidence.observation}</p>}
              </div>
            ))}
          </section>
          <div className="risk-detail-grid">
            <section>
              <h3>可能影响</h3>
              <p>{item.risk.impact}</p>
            </section>
            <section>
              <h3>待确认事项</h3>
              <ul>
                {item.risk.questions.map((question, index) => (
                  <li key={index}>{question}</li>
                ))}
              </ul>
            </section>
          </div>
          <section className="risk-detail-section">
            <h3>
              完善建议 <Badge>需人工确认</Badge>
            </h3>
            <p>{item.risk.improvement.proposal}</p>
            <p className="hint">
              理由：{item.risk.improvement.rationale}
              <br />
              取舍：{item.risk.improvement.tradeoffs}
            </p>
          </section>
          <section className="risk-detail-section">
            <h3>人工处理</h3>

            <FormSelect
              label="处理状态"
              value={state}
              onChange={(value) => setState(value as RiskState)}
              disabled={busy}
              options={Object.entries(riskStates).map(([value, label]) => ({ value, label }))}
            />
            <label className="form-field">
              处理结论
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                required={state !== 'PENDING'}
                maxLength={3000}
                rows={3}
                disabled={busy}
              />
            </label>
          </section>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="row prototype-editor-footer">
          {functionKey && (
            <Link
              className="action ghost"
              to={`/requirements/chat/${item.report_id}?function=${encodeURIComponent(functionKey)}&risk=${encodeURIComponent(item.risk_key)}`}
            >
              围绕此风险追问
            </Link>
          )}

          <button type="button" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="primary" disabled={busy}>
            保存处理
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}

export function reportMarkdown(d: RiskDetail): string {
  const r = d.report;
  let text = `# ${d.title}\n\n导入：${d.created_by} · ${d.created_at}\n状态：${outcomes[r.outcome]}\n\n> 文字证据与导入输入核对，原件由导入者关联；报告不表示测试通过。\n\n## 总体结论\n\n${r.summary.conclusion}\n\n## 功能清单\n\n`;
  for (const f of r.functions)
    text += `### ${f.module} / ${f.name}\n\n${f.scope}\n关联风险：${f.risk_keys.join('、') || '无'}\n\n`;
  const evidence = (values: Evidence[]) =>
    values
      .map(
        (e) =>
          `- ${d.input.materials.find((m) => m.source_id === e.source_id)?.name || e.source_id} / ${e.location}\n  原文：${e.excerpt}\n  观察：${e.observation}`,
      )
      .join('\n');
  text += '## 风险与处理\n\n';
  for (const risk of r.risks) {
    const h = d.handling.find((h) => h.risk_key === risk.key);
    text += `### ${risk.key} ${risk.title}\n\n等级：${riskLevels[risk.severity]} · ${risk.severity_reason}\n\n${risk.description}\n\n影响：${risk.impact}\n\n待确认：${risk.questions.join('；')}\n\n建议：${risk.improvement.proposal}\n理由：${risk.improvement.rationale}\n取舍：${risk.improvement.tradeoffs}\n\n${evidence(risk.evidence)}\n\n处理：${riskStates[h?.status || 'PENDING']}\n人工结论：${h?.note || '尚未填写'}\n\n`;
    if (risk.source_comparison)
      text +=
        '来源对比：\n' +
        risk.source_comparison.sides
          .map((s) => s.statement + '\n' + evidence(s.evidence))
          .join('\n') +
        `\n已知：${risk.source_comparison.known_facts}\n未知：${risk.source_comparison.unknowns}\n\n`;
    for (const a of h?.history || [])
      text += `处理记录：${a.actor} ${a.time} ${riskStates[a.from]} → ${riskStates[a.to]}：${a.note}\n`;
  }
  text +=
    '\n## 可选优化（不计风险）\n\n' +
    r.optional_suggestions
      .map((s) => `### ${s.title}\n${s.proposal}\n理由：${s.rationale}\n取舍：${s.tradeoffs}`)
      .join('\n\n');
  text +=
    '\n\n## 覆盖与边界\n\n' +
    r.coverage
      .map(
        (c) =>
          `${c.source_id}：${c.limitation}\n` +
          c.segments
            .map(
              (s) =>
                `${s.segment_id} / ${s.disposition}：${s.reason}；功能 ${s.function_keys.join('、')}；风险 ${s.risk_keys.join('、')}`,
            )
            .join('\n'),
      )
      .join('\n\n');
  return text + '\n\n' + r.limitations.map((l) => `${l.detail}\n影响：${l.effect}`).join('\n\n');
}
