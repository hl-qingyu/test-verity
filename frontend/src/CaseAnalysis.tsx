import { AnalysisCandidateReview } from './AnalysisCandidateReview';
import { useCachedView } from './pageViewCache';
import type { PageViewCache } from './pageViewCache';
import { AIConfigurationSummary } from './AIConfigurationSummary';
import { callModeName } from './aiConfiguration';
import { AnalysisRecordDelete } from './AnalysisRecordDelete';
import { PageJump } from './PageJump';
import { AcceptancePanel } from './AnalysisAcceptance';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ComponentProps } from 'react';
import type { Project } from './Projects';
import type { User } from './Auth';
import type { OverviewTarget } from './OverviewEntry';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { FilePicker } from './FilePicker';
import { CaseAnalysisNew } from './CaseAnalysisNew';
import { DESIGN_FIELDS, CASE_COLUMNS, blankDesign } from './caseApi';
import type { CaseList, Design, CaseRow } from './caseApi';
import { parseCodeOptions } from './codeAnalysisApi';
import type { CodeOptions } from './codeAnalysisApi';
import { parsePrototypeLibrary } from './prototypeApi';
import type { PrototypeSource } from './prototypeApi';
import { apiRequest } from './api/http';
import { generationCaseSnapshot } from './generationRead';
import { downloadGeneration, caseDesignXlsx } from './generationExport';
import {
  allReviewFindings,
  parseReview,
  parseReviewSummary,
  reviewKinds,
  reviewRequest,
  reviewStates,
  taskStates,
  reviewError,
  reviewText,
  reviewFieldName,
  reviewErrors,
  reviewDiagnostics,
} from './caseAnalysisApi';
import type { ReviewRecord, ReviewFinding, ReviewSummary, ReviewPreview } from './caseAnalysisApi';
import './code-analysis.css';
import './change-analysis.css';
import './case-generation.css';
import './case-analysis.css';

type Props = {
  pageCache?: PageViewCache;
  onRecordDeleted?: () => void;
  project: Project | null;
  user: User;
  onSessionEnd: () => void;
  overviewTarget?: OverviewTarget | null;
};
export function CaseAnalysis(props: Props) {
  const [deletionVersion, setDeletionVersion] = useState(0);
  return (
    <ReviewWorkspace
      key={`${props.user.id}:${props.project?.id}:${deletionVersion}`}
      {...props}
      overviewTarget={deletionVersion ? null : props.overviewTarget}
      onRecordDeleted={() => {
        props.pageCache?.delete('selected');
        setDeletionVersion((v) => v + 1);
      }}
    />
  );
}
function ReviewWorkspace({
  project,
  user,
  onSessionEnd,
  overviewTarget,
  onRecordDeleted,
  pageCache,
}: Props) {
  const [rows, setRows] = useState<ReviewSummary[]>([]),
    [selected, setSelected] = useCachedView(pageCache, 'selected', overviewTarget?.id || 0),
    [record, setRecord] = useState<ReviewRecord | null>(null),
    [loaded, setLoaded] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [tab, setTab] = useCachedView(pageCache, 'tab', 'findings'),
    [page, setPage] = useCachedView(pageCache, 'page', 1),
    [listPage, setListPage] = useState(1),
    [more, setMore] = useState(false),
    [kind, setKind] = useCachedView(pageCache, 'kind', '全部类型'),
    [state, setState] = useCachedView(pageCache, 'state', overviewTarget?.state || '全部状态'),
    [severity, setSeverity] = useCachedView(pageCache, 'severity', '全部等级');
  const [create, setCreate] = useState(false),
    [parent, setParent] = useState<number | undefined>(),
    [options, setOptions] = useState<CodeOptions | null>(null),
    [prototypes, setPrototypes] = useState<PrototypeSource[]>([]),
    [snapshot, setSnapshot] = useState<CaseList | null>(null),
    [detail, setDetail] = useState<string | null>(null),
    [draft, setDraft] = useState<string | null>(null),
    [review, setReview] = useState<ReviewPreview[] | null>(null),
    [importing, setImport] = useState(false),
    [reference, setReference] = useState(''),
    [functionKey, setFunctionKey] = useState(''),
    [manualTurn, setManualTurn] = useState<number | null>(null),
    [fixedCase, setFixedCase] = useState<CaseRow | null>(null);
  const lock = useRef(false),
    alive = useRef(true),
    epoch = useRef(0),
    selection = useRef(selected),
    currentRecord = useRef(record);
  currentRecord.current = record;
  selection.current = selected;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!project) return;
      const value = await reviewRequest(
        project.id,
        `?page=${listPage}`,
        (v) => {
          const o = v as { items: unknown[]; has_more: boolean };
          if (!Array.isArray(o.items) || typeof o.has_more !== 'boolean')
            throw Error('case_analysis_response_invalid');
          return { items: o.items.map(parseReviewSummary), has_more: o.has_more };
        },
        undefined,
        signal,
      );
      if (signal?.aborted || !alive.current) return;
      setRows((old) =>
        listPage === 1
          ? [
              ...value.items,
              ...old.filter(
                (r) => r.id === overviewTarget?.id && !value.items.some((x) => x.id === r.id),
              ),
            ]
          : [...old.filter((r) => !value.items.some((x) => x.id === r.id)), ...value.items],
      );
      setMore(value.has_more);
      setLoaded(true);
      if (!selection.current && value.items[0]) setSelected(value.items[0].id);
    },
    [project, listPage, overviewTarget, setSelected],
  );
  useEffect(() => {
    const c = new AbortController();
    void load(c.signal).catch((e) => {
      if (
        !c.signal.aborted &&
        e instanceof Error &&
        ['not_authenticated', 'project_not_found'].includes(e.message)
      ) {
        setRows([]);
        setRecord(null);
        setLoaded(true);
      }
      if (!c.signal.aborted) setError(reviewError(e, onSessionEnd));
    });
    return () => c.abort();
  }, [load, onSessionEnd]);
  useEffect(() => {
    if (!project || !selected) return;
    const c = new AbortController(),
      version = ++epoch.current;
    setRecord(null);
    setError('');
    let running = false;
    async function refresh() {
      if (running) return;
      running = true;
      try {
        const current = currentRecord.current;
        if (current?.id === selected) {
          const stamp = await reviewRequest(
            project!.id,
            `/${selected}?summary=true`,
            parseReviewSummary,
            undefined,
            c.signal,
          );
          const working =
            ['QUEUED', 'RUNNING'].includes(current.status) ||
            current.chat.some((t) => ['QUEUED', 'RUNNING'].includes(t.status)) ||
            current.applications.some((a) => ['QUEUED', 'RUNNING'].includes(a.status));
          if (
            !working &&
            stamp.updated_at === current.updated_at &&
            stamp.revision === current.revision &&
            stamp.status === current.status
          )
            return;
        }
        const value = await reviewRequest(
          project!.id,
          `/${selected}`,
          parseReview,
          undefined,
          c.signal,
        );
        if (!c.signal.aborted && epoch.current === version) {
          const current = currentRecord.current;
          if (
            current?.id === value.id &&
            (current.revision > value.revision || current.updated_at > value.updated_at)
          )
            return;
          setRecord(value);
          setRows((old) => [value, ...old.filter((r) => r.id !== value.id)]);
        }
      } catch (e) {
        if (
          !c.signal.aborted &&
          e instanceof Error &&
          ['not_authenticated', 'project_not_found'].includes(e.message)
        ) {
          setRows([]);
          setRecord(null);
        }
        if (!c.signal.aborted) setError(reviewError(e, onSessionEnd));
      } finally {
        running = false;
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      c.abort();
      clearInterval(timer);
    };
  }, [project, selected, onSessionEnd]);
  async function action(path: string, body?: unknown) {
    if (!project || lock.current) return null;
    lock.current = true;
    setBusy(true);
    setError('');
    const current = selection.current;
    try {
      const value = await reviewRequest(project.id, path, parseReview, body);
      if (alive.current) {
        if (
          selection.current === current ||
          path === '/prepare' ||
          path === '/import' ||
          path.includes('/retry')
        ) {
          setSelected(value.id);
          setRecord(value);
          setRows((old) => [value, ...old.filter((r) => r.id !== value.id)]);
        }
      }
      return value;
    } catch (e) {
      if (alive.current) setError(reviewError(e, onSessionEnd));
      return null;
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function newAnalysis(parentId?: number) {
    if (!project || lock.current) return;
    setBusy(true);
    setError('');
    try {
      const c = new AbortController();
      const [o, p, s] = await Promise.all([
        apiRequest<unknown>(`/api/projects/${project.id}/code-analysis/options`, {
          signal: c.signal,
        }).then(parseCodeOptions),
        apiRequest<unknown>(`/api/projects/${project.id}/prototypes`, { signal: c.signal }).then(
          parsePrototypeLibrary,
        ),
        generationCaseSnapshot(project.id, c.signal),
      ]);
      if (!alive.current) return;
      setOptions(o);
      setPrototypes(p.sources);
      setSnapshot(s);
      setParent(parentId);
      setCreate(true);
    } catch (e) {
      setError(reviewError(e, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  async function openReview() {
    if (!project || !record) return;
    setError('');
    try {
      const value = await apiRequest<{ items: ReviewPreview[] }>(
        `/api/projects/${project.id}/case-analysis/${record.id}/preview`,
      );
      if (!Array.isArray(value.items)) throw Error('case_analysis_response_invalid');
      setReview(value.items);
      setSnapshot(await generationCaseSnapshot(project.id, new AbortController().signal));
    } catch (e) {
      setError(reviewError(e, onSessionEnd));
    }
  }
  if (!project) return <section className="panel panel-pad">请选择项目。</section>;
  const findings = record ? allReviewFindings(record) : [],
    filtered = findings.filter(
      (f) =>
        (kind === '全部类型' || reviewKinds[f.kind] === kind) &&
        (state === '全部状态' || (record?.handling[f.key]?.state || '待确认') === state) &&
        (severity === '全部等级' || f.severity === severity),
    ),
    cases = record?.input.cases || [],
    complete = record?.status === 'COMPLETED',
    diagnostics = record ? reviewDiagnostics(record) : null;
  function exportRecord() {
    if (!record) return;
    const designs = Object.values(record.handling)
      .filter((h) => h.draft)
      .map((h) => h.draft!);
    if (designs.length) downloadGeneration(record.title + '-候选.xlsx', caseDesignXlsx(designs));
    downloadGeneration(record.title + '-input.json', JSON.stringify(record.input, null, 2), true);
    if (!complete) {
      downloadGeneration(
        record.title + '-执行诊断.json',
        JSON.stringify(record.attempts, null, 2),
        true,
      );
      return;
    }
    downloadGeneration(record.title + '-report.json', JSON.stringify(record.report, null, 2), true);
    downloadGeneration(
      record.title + '-处理审计.json',
      JSON.stringify(
        { handling: record.handling, applications: record.applications, chat: record.chat },
        null,
        2,
      ),
      true,
    );
    downloadGeneration(
      record.title + '.md',
      `# ${record.title}\n\n固定范围${cases.length}条；${record.outcome || record.status}；AI声明不代表测试通过。\n\n` +
        findings
          .map(
            (f) =>
              `## ${f.key} ${reviewText(f.title)}\n\n${reviewText(f.description)}\n\n影响：${reviewText(f.impact)}\n\n建议：${reviewText(f.suggestion)}\n\n${f.evidence.map((e) => `${e.source}：${e.quote}`).join('\n')}\n\n人工处理：${record.handling[f.key]?.state || '待确认'} ${record.handling[f.key]?.comment || ''}\n`,
          )
          .join('\n'),
    );
  }
  return (
    <div className="change-analysis-page case-review-page">
      <div className="page-head">
        <div>
          <h1>用例分析</h1>
          <p>需求符合性 · 遗漏场景 · 设计质量</p>
        </div>
        <div className="head-actions">
          <button className="primary" disabled={busy} onClick={() => void newAnalysis()}>
            新建用例分析
          </button>
          <button
            onClick={() => {
              setError('');
              setImport(true);
            }}
          >
            导入分析结果
          </button>
          <button disabled={!record} onClick={exportRecord}>
            导出
          </button>
          <button disabled={!complete || busy} onClick={() => void newAnalysis(record?.id)}>
            关联复核
          </button>
          <Link className="action" to="/cases">
            打开用例管理
          </Link>
        </div>
      </div>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <section className="code-analysis-overview">
        <div>
          <div className="eyebrow">用例分析</div>
          <h2>{record?.title || '从现有用例开始'}</h2>
          <p>
            <AIConfigurationSummary value={record?.ai_config} />
          </p>

          <p>
            {record ? taskStates[record.status] : '正在读取记录…'}
            {record?.outcome === 'PARTIAL'
              ? ' · 部分完成'
              : complete
                ? ' · AI声明范围完成，待人工核对'
                : ''}
          </p>
        </div>
        <div className="code-analysis-stats">
          {[
            [
              '用例问题',
              complete
                ? findings.filter((f) => ['MISMATCH', 'QUALITY'].includes(f.kind)).length
                : '—',
            ],
            ['缺失场景', complete ? findings.filter((f) => f.kind === 'MISSING').length : '—'],
            [
              '待澄清 / 准备',
              complete
                ? findings.filter((f) => ['SETUP', 'QUESTION'].includes(f.kind)).length
                : '—',
            ],
          ].map(([n, v]) => (
            <span key={n}>
              <strong>{v}</strong>
              <small>{n}</small>
            </span>
          ))}
        </div>
      </section>
      {project && record && (
        <AcceptancePanel
          projectId={project.id}
          module="coverage"
          refreshKey={record.revision}
          recordId={record.id}
          onSessionEnd={onSessionEnd}
        />
      )}
      <div className="code-analysis-layout">
        <aside className="panel code-analysis-records">
          <div className="panel-head">
            <h2>分析记录</h2>
            <span className="badge">{rows.length}</span>
          </div>
          {rows.map((r) => (
            <div className="analysis-record-row" key={r.id}>
              <button
                className={`code-record ${r.id === selected ? 'active' : ''}`}
                aria-current={r.id === selected ? 'true' : undefined}
                onClick={() => {
                  setSelected(r.id);
                  setState('全部状态');
                  setPage(1);
                  setReference('');
                }}
              >
                <strong>{r.title}</strong>
                <small>
                  {r.mode === 'COMPARE' ? '对照需求' : '仅检查质量'} · {taskStates[r.status]}
                </small>
                <small>
                  {new Date(r.created_at)
                    .toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' })
                    .slice(0, 16)}{' '}
                  · {r.actor_id === user.id ? user.display_name : '账号' + r.actor_id}
                </small>
              </button>
              {project && (
                <AnalysisRecordDelete
                  base={`/api/projects/${project.id}/case-analysis`}
                  id={r.id}
                  projectId={project.id}
                  iconOnly
                  recordTitle={r.title}
                  canDelete={
                    user.platform_role === 'ADMIN' || project.can_manage || r.actor_id === user.id
                  }
                  refreshKey={`${r.status}:${r.revision}`}
                  onDeleted={onRecordDeleted}
                  onSessionEnd={onSessionEnd}
                />
              )}
            </div>
          ))}
          {loaded && !rows.length && <p className="hint panel-pad">暂无分析记录</p>}
          {more && (
            <button className="ghost small" onClick={() => setListPage((p) => p + 1)}>
              更多记录
            </button>
          )}
        </aside>
        <section className="panel code-analysis-main">
          <div className="change-result-tabs tabs" role="tablist" aria-label="用例分析结果">
            {[
              ['findings', '分析问题'],
              ['checks', '用例检查'],
              ['chat', '对话'],
            ].map(([k, n]) => (
              <button
                role="tab"
                aria-selected={tab === k}
                className={tab === k ? 'active' : ''}
                key={k}
                onClick={() => {
                  setTab(k);
                  setPage(1);
                }}
              >
                {n}
              </button>
            ))}
          </div>
          {!record ? (
            <div className="panel-pad">
              {selected ? '正在读取固定记录…' : '新建分析后展示结果。'}
            </div>
          ) : tab === 'chat' ? (
            <ReviewChat
              record={record}
              functionKey={functionKey}
              setFunctionKey={setFunctionKey}
              reference={reference}
              setReference={setReference}
              busy={busy}
              onSend={(body) => action(`/${record.id}/chat`, body)}
              onManual={setManualTurn}
            />
          ) : !complete ? (
            <section className="panel-pad">
              <h3>{taskStates[record.status]}</h3>
              <p className="hint">{record.notice}</p>
              {diagnostics && (
                <p className="hint" role="status">
                  阶段：
                  {(
                    {
                      preparing: '准备中',
                      request_sent: '已发送',
                      connected: '已连接',
                      receiving: '接收中',
                      validating_response: '校验响应',
                      validating_report: '校验报告',
                      completed: '调用完成',
                    } as Record<string, string>
                  )[diagnostics.phase] || '等待'}{' '}
                  · 耗时{diagnostics.elapsed ?? '—'}秒 · 接收{diagnostics.bytes ?? '—'}字节 · 输出
                  {diagnostics.characters ?? '—'}字符
                </p>
              )}
              <p>
                本人AI：
                {record.personal_ai
                  ? `${callModeName(record.personal_ai.call_mode)} / ${record.personal_ai.name} / ${record.personal_ai.model}`
                  : '请先配置个人AI'}
              </p>
              {record.status === 'FAILED' &&
                record.attempts.some(
                  (entry) =>
                    !!entry &&
                    typeof entry === 'object' &&
                    'raw_response' in entry &&
                    !!entry.raw_response,
                ) && (
                  <AnalysisCandidateReview
                    endpoint={`/api/projects/${project.id}/case-analysis/${record.id}/candidate-review`}
                    onSessionEnd={onSessionEnd}
                  />
                )}
              {record.error_code && (
                <p className="inline-error">
                  {reviewErrors[record.error_code] || '分析未完成，请核对后重试。'}
                </p>
              )}
              <div className="row">
                {record.status === 'PREPARED' && (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() =>
                      void action(`/${record.id}/start`, {
                        revision: record.revision,
                        confirmed: true,
                        ai_version: record.personal_ai?.version || null,
                        ai_call_mode: record.personal_ai?.call_mode,
                        ai_preference_version: record.personal_ai?.preference_version,
                      })
                    }
                  >
                    核对范围并开始本人AI分析
                  </button>
                )}
                {['QUEUED', 'RUNNING'].includes(record.status) && (
                  <>
                    <span className="generation-spinner" aria-hidden="true" />
                    <span role="status">
                      {taskStates[record.status]} · 离开页面继续；不显示虚构百分比
                    </span>
                    <button
                      disabled={busy || user.id !== record.actor_id}
                      onClick={() => void action(`/${record.id}/cancel`, {})}
                    >
                      取消（仅发起人）
                    </button>
                  </>
                )}
                {['FAILED', 'CANCELLED'].includes(record.status) && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void action(`/${record.id}/retry?request_id=${crypto.randomUUID()}`, {})
                    }
                  >
                    人工重试固定输入
                  </button>
                )}
              </div>
            </section>
          ) : tab === 'checks' ? (
            <>
              <div className="review-results">
                {cases.slice((page - 1) * 10, page * 10).map((c) => {
                  const issue = findings.filter((f) => f.case_ids.includes(c.id)),
                    checked = record.report.checked_case_ids?.includes(c.id);
                  return (
                    <article className="rule-card" key={c.id}>
                      <div className="between">
                        <strong>
                          {c.number} · {c.title}
                        </strong>
                        <span className={`badge ${checked ? 'blue' : 'orange'}`}>
                          {checked
                            ? issue.length
                              ? '已检查，有问题'
                              : '已检查，未发现问题'
                            : '尚未检查'}
                        </span>
                      </div>
                      <p className="hint">
                        设计版本 v{c.version} · {c.lifecycle === 'RETIRED' ? '已停用' : '活动'} ·{' '}
                        {c.category_id
                          ? snapshot?.categories.find((x) => x.id === c.category_id)?.name ||
                            '已分类'
                          : '未分类'}
                      </p>
                      <div className="row review-check-actions">
                        {issue.map((f) => (
                          <button className="link" key={f.key} onClick={() => setDetail(f.key)}>
                            {reviewText(f.title)}
                          </button>
                        ))}
                        <button className="small" onClick={() => setFixedCase(c)}>
                          查看固定用例
                        </button>
                      </div>
                    </article>
                  );
                })}
                {!cases.length && <p>本次0条用例，仅识别缺失场景。</p>}
              </div>
              <Pagination page={page} count={cases.length} onChange={setPage} />
            </>
          ) : (
            <>
              <div className="code-filters">
                <FormSelect
                  label="问题类型"
                  value={kind}
                  options={['全部类型', ...Object.values(reviewKinds)].map((value) => ({
                    value,
                    label: value,
                  }))}
                  onChange={(v) => {
                    setKind(v);
                    setPage(1);
                  }}
                />
                <FormSelect
                  label="风险等级"
                  value={severity}
                  options={['全部等级', '高', '中', '低'].map((value) => ({ value, label: value }))}
                  onChange={(v) => {
                    setSeverity(v);
                    setPage(1);
                  }}
                />
                <FormSelect
                  label="处理状态"
                  value={state}
                  options={['全部状态', ...reviewStates].map((value) => ({ value, label: value }))}
                  onChange={(v) => {
                    setState(v);
                    setPage(1);
                  }}
                />
              </div>
              <div className="review-results">
                {record.outcome === 'PARTIAL' && (
                  <p className="evidence">部分完成，未检查的用例不能视为符合需求。</p>
                )}
                {filtered.slice((page - 1) * 10, page * 10).map((f) => (
                  <article className="rule-card" key={f.key}>
                    <div className="between">
                      <h3>{reviewText(f.title)}</h3>
                      <span className={`badge ${f.severity === '高' ? 'red' : 'orange'}`}>
                        {f.severity}
                      </span>
                    </div>
                    <div className="row review-badges">
                      <span className="badge">{reviewKinds[f.kind]}</span>
                      <span className="badge">{record.handling[f.key]?.state || '待确认'}</span>
                      {record.handling[f.key]?.draft && (
                        <span className="badge blue">
                          {record.handling[f.key]?.applied ? '草案已应用' : '有人工草案'}
                        </span>
                      )}
                    </div>
                    <p>{reviewText(f.impact)}</p>
                    <p className="hint">
                      {f.case_ids
                        .map((id) => cases.find((c) => c.id === id)?.number || id)
                        .join('、') || '本次范围事项，无现成用例'}
                    </p>
                    <div className="row review-card-actions">
                      <button className="small" onClick={() => setDetail(f.key)}>
                        查看详情
                      </button>
                      <button
                        className="ghost small"
                        onClick={() => {
                          setReference(f.key);
                          setTab('chat');
                        }}
                      >
                        追问
                      </button>
                    </div>
                  </article>
                ))}
                {!filtered.length && <p className="hint">当前筛选未发现问题。</p>}
              </div>
              <Pagination page={page} count={filtered.length} onChange={setPage} />
              <div className="review-bottom between">
                <span className="hint">问题处理与用例审核分别保留</span>
                <button
                  className="primary"
                  disabled={
                    busy || !Object.values(record.handling).some((h) => h.draft && !h.applied)
                  }
                  onClick={() => void openReview()}
                >
                  审核用例草案
                </button>
              </div>
            </>
          )}
        </section>
        <aside className="panel code-analysis-context">
          <h2>固定依据与范围</h2>
          <p>
            {record?.mode === 'QUALITY' ? '仅检查用例质量，没有需求对照' : '对照所选需求及原型'}
          </p>
          {record?.input.materials.map((m) => (
            <section className="evidence" key={m.source_id}>
              <strong>{m.name}</strong>
              <p className="hint">
                {m.version}
                <br />
                {m.read_note}
                <br />
                {m.segments.length}个已保存内容片段
              </p>
            </section>
          ))}
          <section className="evidence">
            固定{cases.length}条用例；仅本次范围作结论。
            {record?.parent_id && <p>关联来源记录{record.parent_id}</p>}
          </section>
          <p className="hint">{record?.input.focus}</p>
        </aside>
      </div>
      {record?.applications.map((a) => (
        <section className="evidence mt" key={a.id}>
          <strong>
            审核申请{a.id} · {taskStates[a.status]}
          </strong>
          <p>
            成功{a.items.filter((i) => i.status === 'SUCCESS').length} / 失败
            {a.items.filter((i) => i.status === 'FAILED').length} / 待处理
            {a.items.filter((i) => i.status === 'PENDING').length}
          </p>
          {a.items
            .filter((i) => i.error_code)
            .map((i) => (
              <p className="inline-error" key={i.key}>
                {i.key}：{reviewErrors[i.error_code || ''] || '本条处理失败，请重新核对。'}
              </p>
            ))}
        </section>
      ))}
      {fixedCase && (
        <ReviewDialog
          title={`固定用例 · ${fixedCase.number} / v${fixedCase.version}`}
          busy={false}
          onClose={() => setFixedCase(null)}
          wide
          footer={<button onClick={() => setFixedCase(null)}>关闭</button>}
        >
          <DesignContent design={fixedCase} />
        </ReviewDialog>
      )}
      {create && options && snapshot && (
        <CaseAnalysisNew
          projectId={project.id}
          parentId={parent}
          options={options}
          prototypes={prototypes}
          snapshot={snapshot}
          busy={busy}
          error={error}
          onClose={() => setCreate(false)}
          onSessionEnd={onSessionEnd}
          onPrepare={async (v) => {
            if (await action('/prepare', v)) setCreate(false);
          }}
        />
      )}
      {detail && record && (
        <ReviewDetail
          key={detail}
          record={record}
          finding={findings.find((f) => f.key === detail)!}
          sequence={filtered.map((f) => f.key)}
          busy={busy}
          error={error}
          onClose={() => setDetail(null)}
          onSave={(v) => action(`/${record.id}/handling`, v)}
          onNavigate={(k) => {
            setDetail(k);
            setPage(Math.floor(filtered.findIndex((f) => f.key === k) / 10) + 1);
          }}
          onDraft={() => {
            setDraft(detail);
            setDetail(null);
          }}
          onAsk={() => {
            setReference(detail);
            setDetail(null);
            setTab('chat');
          }}
        />
      )}
      {draft && record && (
        <ReviewDraft
          key={draft}
          record={record}
          finding={findings.find((f) => f.key === draft)!}
          projectId={project.id}
          busy={busy}
          error={error}
          onClose={() => setDraft(null)}
          onSave={async (v) => {
            if (await action(`/${record.id}/handling`, v)) setDraft(null);
          }}
          onSessionEnd={onSessionEnd}
        />
      )}{' '}
      {review && record && snapshot && (
        <ReviewAudit
          items={review}
          categories={snapshot.categories}
          busy={busy}
          error={error}
          onClose={() => setReview(null)}
          onSubmit={async (v) => {
            if (await action(`/${record.id}/apply`, v)) setReview(null);
          }}
        />
      )}
      {importing && (
        <ReviewImport
          busy={busy}
          error={error}
          onClose={() => setImport(false)}
          onImport={async (v) => {
            if (await action('/import', v)) setImport(false);
          }}
        />
      )}
      {manualTurn && record && (
        <ReviewManual
          record={record}
          turnId={manualTurn}
          busy={busy}
          error={error}
          onClose={() => setManualTurn(null)}
          onSave={async (v) => {
            if (await action(`/${record.id}/from-chat`, v)) {
              setManualTurn(null);
              setTab('findings');
            }
          }}
        />
      )}
    </div>
  );
}
function ReviewDialog({ footer, className = '', ...props }: ComponentProps<typeof CaseDialog>) {
  return (
    <CaseDialog
      {...props}
      className={`case-review-dialog ${className}`}
      footer={<footer className="change-dialog-footer review-dialog-footer">{footer}</footer>}
    />
  );
}
function Pagination({
  page,
  count,
  onChange,
}: {
  page: number;
  count: number;
  onChange: (v: number) => void;
}) {
  return (
    <nav className="code-analysis-pagination between">
      <span>
        {count}条 · 第{page}/{Math.max(1, Math.ceil(count / 10))}页
      </span>
      <div className="row">
        <button disabled={page === 1} onClick={() => onChange(page - 1)}>
          上一页
        </button>
        <button disabled={page * 10 >= count} onClick={() => onChange(page + 1)}>
          下一页
        </button>
        <PageJump page={page} onChange={onChange} pages={Math.max(1, Math.ceil(count / 10))} />
      </div>
    </nav>
  );
}
function DesignContent({ design }: { design: Design }) {
  return (
    <div className="review-design">
      {['preconditions', 'data_requirements', 'steps', 'expected'].map((k) => (
        <section key={k}>
          <strong>{reviewFieldName(k)}</strong>
          <p className="review-text">{design[k as keyof Design] || '未填写'}</p>
        </section>
      ))}
      <details>
        <summary>其他字段</summary>
        {DESIGN_FIELDS.filter(
          (k) => !['preconditions', 'data_requirements', 'steps', 'expected'].includes(k),
        ).map((k) => (
          <p key={k}>
            {reviewFieldName(k)}：{design[k]}
          </p>
        ))}
      </details>
    </div>
  );
}
function Evidence({ record, finding }: { record: ReviewRecord; finding: ReviewFinding }) {
  return (
    <>
      {finding.evidence.map((e, i) => {
        const matches = record.input.materials.filter((m) => m.source_id === e.source),
          m = matches.length === 1 ? matches[0] : null,
          s = m?.segments.find((s) => s.text.includes(e.quote));
        return (
          <section className="evidence" key={i}>
            <strong>{m?.name || e.source}</strong>
            <p className="hint">
              {m?.version} · {s?.location || '无唯一位置'}
            </p>
            <p className="review-text">
              {e.observation
                ? 'AI附件观察（待人工核对）：' + e.observation
                : s
                  ? e.quote
                  : '未保存可核对的本条摘录'}
            </p>
          </section>
        );
      })}
      {!finding.evidence.length && (
        <p className="hint">
          {record.mode === 'QUALITY'
            ? '仅质量检查，无需求对照。'
            : '没有本条需求摘录，不推定业务规则。'}
        </p>
      )}
    </>
  );
}
function ReviewDetail({
  record,
  finding,
  sequence,
  busy,
  error,
  onClose,
  onSave,
  onNavigate,
  onDraft,
  onAsk,
}: {
  record: ReviewRecord;
  finding: ReviewFinding;
  sequence: string[];
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (v: unknown) => Promise<ReviewRecord | null>;
  onNavigate: (k: string) => void;
  onDraft: () => void;
  onAsk: () => void;
}) {
  const h = record.handling[finding.key] || {},
    [state, setState] = useState(h.state || '待确认'),
    [comment, setComment] = useState(h.comment || ''),
    revision = useRef(record.revision),
    [localError, setLocalError] = useState('');
  async function save(next?: () => void) {
    if (state !== '待确认' && !comment.trim()) {
      setLocalError('确认、解决或不适用需要填写说明。');
      return;
    }
    if (state !== (h.state || '待确认') || comment !== (h.comment || '')) {
      if (!(await onSave({ revision: revision.current, key: finding.key, state, comment }))) return;
    }
    next?.();
  }
  const index = sequence.indexOf(finding.key);
  return (
    <ReviewDialog
      title={`分析详情 · ${finding.key}`}
      busy={busy}
      onClose={onClose}
      wide
      className="generation-detail-dialog"
      sideControls={
        <div className="generation-detail-switcher">
          <button
            className="generation-detail-nav"
            aria-label="上一条问题"
            disabled={busy || index <= 0}
            onClick={() => void save(() => onNavigate(sequence[index - 1]))}
          >
            ‹
          </button>
          <button
            className="generation-detail-nav"
            aria-label="下一条问题"
            disabled={busy || index < 0 || index >= sequence.length - 1}
            onClick={() => void save(() => onNavigate(sequence[index + 1]))}
          >
            ›
          </button>
        </div>
      }
      footer={
        <>
          <button onClick={onClose}>关闭</button>
          <button disabled={busy} onClick={() => void save(onAsk)}>
            追问
          </button>
          {!['SETUP', 'QUESTION'].includes(finding.kind) && !h.applied && (
            <button disabled={busy} onClick={() => void save(onDraft)}>
              {finding.kind === 'MISSING' ? '准备补充用例' : '准备修改用例'}
            </button>
          )}
          <button className="primary" form="reviewHandle" disabled={busy}>
            保存处理
          </button>
        </>
      }
    >
      <div className="row review-badges">
        <span className="badge">{reviewKinds[finding.kind]}</span>
        <span className={`badge ${finding.severity === '高' ? 'red' : 'orange'}`}>
          风险{finding.severity}
        </span>
      </div>
      <h2 className="review-detail-title">{reviewText(finding.title)}</h2>
      <p>{reviewText(finding.description)}</p>
      <section className="evidence">
        <strong>影响与建议</strong>
        <p>{reviewText(finding.impact)}</p>
        <p>{reviewText(finding.suggestion)}</p>
        <p className="hint">等级理由：{reviewText(finding.reason)}</p>
      </section>
      <h3>本条需求依据</h3>
      <Evidence record={record} finding={finding} />
      {finding.case_ids.map((id) => {
        const c = record.input.cases.find((c) => c.id === id);
        return (
          c && (
            <details className="evidence" key={id} open>
              <summary>
                固定用例{c.number} / v{c.version} · {finding.fields.map(reviewFieldName).join('、')}
              </summary>
              <DesignContent design={c} />
            </details>
          )
        );
      })}
      <Form
        id="reviewHandle"
        onSubmit={(e) => {
          e.preventDefault();
          void save(onClose);
        }}
      >
        <FormSelect
          label="处理状态"
          value={state}
          options={reviewStates.map((value) => ({ value, label: value }))}
          onChange={setState}
        />
        <label className="field-label">
          人工说明
          <textarea
            required={state !== '待确认'}
            value={comment}
            maxLength={10000}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
      </Form>
      <p className="hint">入库不会自动关闭问题。</p>
      {(error || localError) && (
        <p className="inline-error" role="alert">
          {error || localError}
        </p>
      )}
      <details>
        <summary>处理历史</summary>
        {h.history?.map((e, i) => (
          <p key={i}>
            {e.time} · {e.actor_id} · {e.state} · {e.comment}
          </p>
        ))}
      </details>
    </ReviewDialog>
  );
}
function ReviewDraft({
  record,
  finding,
  projectId,
  busy,
  error,
  onClose,
  onSave,
  onSessionEnd,
}: {
  record: ReviewRecord;
  finding: ReviewFinding;
  projectId: number;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (v: unknown) => Promise<void>;
  onSessionEnd: () => void;
}) {
  const h = record.handling[finding.key] || {},
    fixed = record.input.cases.find((c) => finding.case_ids.includes(c.id)),
    [design, setDesign] = useState<Design>(
      h.draft ||
        (fixed
          ? (Object.fromEntries(DESIGN_FIELDS.map((f) => [f, fixed[f]])) as Design)
          : blankDesign()),
    ),
    [current, setCurrent] = useState<CaseRow | null>(null),
    [snapshot, setSnapshot] = useState<CaseList | null>(null),
    [category, setCategory] = useState(String(h.category_id || 0)),
    [checked, setChecked] = useState(false),
    [localError, setLocalError] = useState('');
  useEffect(() => {
    const c = new AbortController();
    generationCaseSnapshot(projectId, c.signal, true)
      .then((s) => {
        if (c.signal.aborted) return;
        setSnapshot(s);
        setCurrent(s.items.find((c) => c.id === fixed?.id) || null);
      })
      .catch((e) => {
        if (!c.signal.aborted) setLocalError(reviewError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [projectId, fixed?.id, onSessionEnd]);
  return (
    <ReviewDialog
      title="准备用例草案"
      busy={busy}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <button
            form="reviewDraft"
            disabled={busy || !snapshot || !checked || (!!fixed && !current)}
            className="primary"
          >
            保存人工草案
          </button>
        </>
      }
    >
      <p className="hint">草案须审核后入库，缺失场景需补齐设计。</p>
      {fixed && current?.version !== fixed.version && (
        <p className="inline-error">目标设计已变化或删除，请核对当前库内容。</p>
      )}
      <Form
        id="reviewDraft"
        onSubmit={(e) => {
          e.preventDefault();
          void onSave({
            revision: record.revision,
            key: finding.key,
            state: h.state || '待确认',
            comment: h.comment || '',
            draft: design,
            category_id: Number(category) || null,
            evidence_checked: checked,
            target_version: current?.version || null,
          });
        }}
      >
        <fieldset disabled={busy}>
          <div className="form-grid">
            {DESIGN_FIELDS.map((k) =>
              k === 'priority' ? (
                <FormSelect
                  key={k}
                  label="优先级"
                  value={design[k]}
                  options={['', 'P0', 'P1', 'P2', 'P3', 'P4'].map((value) => ({
                    value,
                    label: value || '留空',
                  }))}
                  onChange={(v) => {
                    setDesign((d) => ({ ...d, [k]: v }));
                    setChecked(false);
                  }}
                />
              ) : (
                <label
                  className={`field-label ${['steps', 'expected', 'preconditions', 'remark'].includes(k) ? 'span2' : ''}`}
                  key={k}
                >
                  {CASE_COLUMNS.find(([f]) => f === k)?.[1] ||
                    (
                      { data_requirements: '测试数据要求', cleanup: '清理要求' } as Record<
                        string,
                        string
                      >
                    )[k]}
                  <textarea
                    value={design[k]}
                    required={['title', 'steps', 'expected'].includes(k)}
                    maxLength={k === 'case_type' ? 200 : 30000}
                    onChange={(e) => {
                      setDesign((d) => ({ ...d, [k]: e.target.value }));
                      setChecked(false);
                    }}
                  />
                </label>
              ),
            )}
          </div>
          <FormSelect
            label="用例分类"
            value={category}
            options={[
              { value: '0', label: '未分类' },
              ...(snapshot?.categories || []).map((c) => ({ value: String(c.id), label: c.name })),
            ]}
            onChange={(v) => {
              setCategory(v);
              setChecked(false);
            }}
          />
          <label className="check-label">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => setChecked(e.target.checked)}
            />
            我已核对业务依据、完整设计及当前目标版本
          </label>
        </fieldset>
      </Form>
      <Evidence record={record} finding={finding} />
      {current && (
        <details>
          <summary>当前库设计 v{current.version}</summary>
          <DesignContent design={current} />
        </details>
      )}
      {(error || localError) && <p className="inline-error">{error || localError}</p>}
    </ReviewDialog>
  );
}
function ReviewAudit({
  items,
  categories,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  items: ReviewPreview[];
  categories: CaseList['categories'];
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (v: unknown) => Promise<void>;
}) {
  const [selected, setSelected] = useState(items.map((i) => i.key)),
    [active, setActive] = useState(items[0]?.key || ''),
    [page, setPage] = useState(1),
    [cats, setCats] = useState<Record<string, number | null>>({}),
    [choices, setChoices] = useState<
      Record<
        string,
        { action: string; target_id?: number; target_version?: number; reason?: string }
      >
    >({}),
    [confirmed, setConfirmed] = useState(false);
  const item = items.find((i) => i.key === active),
    request = useRef(crypto.randomUUID());
  function changed() {
    setConfirmed(false);
  }
  return (
    <ReviewDialog
      title="审核用例草案"
      busy={busy}
      onClose={onClose}
      wide
      className="generation-review-dialog"
      footer={
        <>
          <label className="check-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            我已审核这{selected.length}条用例
          </label>
          <button onClick={onClose}>取消</button>
          <button
            disabled={busy || !confirmed || !selected.length}
            className="primary"
            onClick={() =>
              void onSubmit({
                request_id: request.current,
                confirmed: true,
                items: items
                  .filter((i) => selected.includes(i.key))
                  .map((i) => ({
                    ...choices[i.key],
                    key: i.key,
                    draft_revision: i.draft_revision,
                    action: choices[i.key]?.action || 'apply',
                    category_id: cats[i.key] === undefined ? i.category_id : cats[i.key],
                  })),
              })
            }
          >
            确认入库（{selected.length}条）
          </button>
        </>
      }
    >
      <FormSelect
        label="统一分类"
        value=""
        options={[
          { value: '', label: '选择统一分类', disabled: true },
          { value: '0', label: '未分类' },
          ...categories.map((c) => ({ value: String(c.id), label: c.name })),
        ]}
        onChange={(v) => {
          setCats((old) => ({
            ...old,
            ...Object.fromEntries(
              items
                .filter(
                  (i) =>
                    selected.includes(i.key) &&
                    (!i.matches.length || choices[i.key]?.action === 'include'),
                )
                .map((i) => [i.key, Number(v) || null]),
            ),
          }));
          changed();
        }}
      />
      <div className="review-audit-layout">
        <aside>
          <label className="check-label">
            <input
              type="checkbox"
              checked={selected.length === items.length}
              onChange={(e) => {
                setSelected(e.target.checked ? items.map((i) => i.key) : []);
                changed();
              }}
            />
            全选（跨页）
          </label>
          <div className="review-audit-list">
            {items.slice((page - 1) * 10, page * 10).map((i) => (
              <div className="review-audit-row" key={i.key}>
                <input
                  type="checkbox"
                  aria-label={`选择草案${i.key}`}
                  checked={selected.includes(i.key)}
                  onChange={(e) => {
                    setSelected((old) =>
                      e.target.checked ? [...old, i.key] : old.filter((k) => k !== i.key),
                    );
                    changed();
                  }}
                />
                <button
                  className={active === i.key ? 'primary' : ''}
                  onClick={() => setActive(i.key)}
                >
                  {i.design.title}
                </button>
              </div>
            ))}
          </div>
          <Pagination page={page} count={items.length} onChange={setPage} />
        </aside>
        <section>
          {item && (
            <>
              <h3>{item.design.title}</h3>
              <DesignContent design={item.design} />
              <FormSelect
                label="本条分类"
                value={String(
                  cats[item.key] === undefined ? item.category_id || 0 : cats[item.key] || 0,
                )}
                disabled={!!item.matches.length && choices[item.key]?.action !== 'include'}
                options={[
                  { value: '0', label: '未分类' },
                  ...categories.map((c) => ({ value: String(c.id), label: c.name })),
                ]}
                onChange={(v) => {
                  setCats((old) => ({ ...old, [item.key]: Number(v) || null }));
                  changed();
                }}
              />
              {item.target && (
                <details>
                  <summary>修改前后差异</summary>
                  {DESIGN_FIELDS.filter((f) => item.target?.[f] !== item.design[f]).map((f) => (
                    <p className="review-text" key={f}>
                      {reviewFieldName(f)}
                      <br />
                      原：{item.target?.[f]}
                      <br />
                      新：{item.design[f]}
                    </p>
                  ))}
                </details>
              )}
              {!!item.matches.length && (
                <section className="evidence">
                  <strong>相同设计，需人工处理重复</strong>
                  <FormSelect
                    label="处理方式"
                    value={choices[item.key]?.action || 'apply'}
                    options={[
                      { value: 'apply', label: '请选择', disabled: true },
                      { value: 'reuse', label: '关联复用' },
                      { value: 'include', label: '仍然新增' },
                    ]}
                    onChange={(v) => {
                      setChoices((old) => ({
                        ...old,
                        [item.key]: { ...old[item.key], action: v },
                      }));
                      changed();
                    }}
                  />
                  {choices[item.key]?.action === 'reuse' && (
                    <FormSelect
                      label="复用目标"
                      value={String(choices[item.key]?.target_id || '')}
                      options={[
                        { value: '', label: '请选择' },
                        ...item.matches.map((c) => ({
                          value: String(c.id),
                          label: `${c.number} / v${c.version} · ${c.lifecycle === 'RETIRED' ? '停用' : '活动'}`,
                          disabled: c.lifecycle === 'RETIRED',
                        })),
                      ]}
                      onChange={(v) => {
                        setChoices((old) => ({
                          ...old,
                          [item.key]: {
                            ...old[item.key],
                            action: 'reuse',
                            target_id: Number(v),
                            target_version: item.matches.find((c) => c.id === Number(v))?.version,
                          },
                        }));
                        changed();
                      }}
                    />
                  )}
                  <label className="field-label">
                    处理说明
                    <textarea
                      value={choices[item.key]?.reason || ''}
                      onChange={(e) => {
                        setChoices((old) => ({
                          ...old,
                          [item.key]: {
                            ...old[item.key],
                            action: old[item.key]?.action || 'apply',
                            reason: e.target.value,
                          },
                        }));
                        changed();
                      }}
                    />
                  </label>
                  <p className="hint">复用保留旧分类、设计与测试。仍然新增必须说明理由。</p>
                </section>
              )}
            </>
          )}
        </section>
      </div>
      {error && <p className="inline-error">{error}</p>}
      <p className="hint">失败项可单独重试，成功项保留。</p>
    </ReviewDialog>
  );
}
function ReviewChat({
  record,
  functionKey,
  setFunctionKey,
  reference,
  setReference,
  busy,
  onSend,
  onManual,
}: {
  record: ReviewRecord;
  functionKey: string;
  setFunctionKey: (v: string) => void;
  reference: string;
  setReference: (v: string) => void;
  busy: boolean;
  onSend: (v: unknown) => Promise<unknown>;
  onManual: (v: number) => void;
}) {
  const [text, setText] = useState('');
  return (
    <div className="panel-pad review-chat-panel">
      <FormSelect
        label="独立对话范围"
        value={functionKey}
        options={[
          { value: '', label: '本记录整体' },
          ...Array.from(new Set(record.input.cases.map((c) => c.module).filter(Boolean))).map(
            (v) => ({ value: v, label: v }),
          ),
        ]}
        onChange={setFunctionKey}
      />
      {reference && (
        <section className="evidence">
          引用：{allReviewFindings(record).find((f) => f.key === reference)?.title}
          <button className="link" onClick={() => setReference('')}>
            移除引用
          </button>
        </section>
      )}
      <div className="review-chat">
        {record.chat
          .filter((t) => t.function_key === functionKey)
          .map((t) => (
            <article className="evidence" key={t.id}>
              <strong>提问</strong>
              <p className="review-text">{t.question}</p>
              <strong>{taskStates[t.status]}</strong>
              <p className="review-text">
                {t.answer
                  ? reviewText(t.answer)
                  : t.error_code
                    ? reviewErrors[t.error_code] || '回复未完成，请重新核对。'
                    : '等待本人AI回复…'}
              </p>
              {t.status === 'COMPLETED' && (
                <button onClick={() => onManual(t.id)}>添加为待确认事项</button>
              )}
            </article>
          ))}
      </div>
      <Form
        onSubmit={(e) => {
          e.preventDefault();
          void onSend({
            request_id: crypto.randomUUID(),
            question: text,
            finding_key: reference,
            function_key: functionKey,
          }).then((v) => {
            if (v) setText('');
          });
        }}
      >
        <label className="field-label">
          提问
          <textarea
            value={text}
            required
            maxLength={10000}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <button
          className="primary"
          disabled={
            busy ||
            record.chat.some(
              (t) => t.function_key === functionKey && ['RUNNING', 'QUEUED'].includes(t.status),
            )
          }
        >
          使用本人AI发送
        </button>
      </Form>
    </div>
  );
}
function ReviewImport({
  busy,
  error,
  onClose,
  onImport,
}: {
  busy: boolean;
  error: string;
  onClose: () => void;
  onImport: (v: unknown) => Promise<void>;
}) {
  const [input, setInput] = useState<unknown>(),
    [report, setReport] = useState<unknown>(),
    [localError, setError] = useState('');
  async function read(file: File | undefined, set: (v: unknown) => void) {
    if (!file) return;
    try {
      if (file.size > 16 * 1024 * 1024) throw Error('文件超过16MiB限制');
      set(JSON.parse(await file.text()));
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <ReviewDialog
      title="导入固定配对结果"
      busy={busy}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <button
            className="primary"
            disabled={busy || !input || !report}
            onClick={() => void onImport({ input, report })}
          >
            核对并导入
          </button>
        </>
      }
    >
      <p>配对导入本项目准备记录的 input.json 与 report.json；不支持旧覆盖率报告。</p>
      <FilePicker accept=".json" onChange={(files) => void read(files[0], setInput)} />
      <FilePicker accept=".json" onChange={(files) => void read(files[0], setReport)} />
      {(error || localError) && <p className="inline-error">{error || localError}</p>}
    </ReviewDialog>
  );
}
function ReviewManual({
  record,
  turnId,
  busy,
  error,
  onClose,
  onSave,
}: {
  record: ReviewRecord;
  turnId: number;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (v: unknown) => Promise<void>;
}) {
  const [title, setTitle] = useState(''),
    [description, setDescription] = useState(
      record.chat.find((t) => t.id === turnId)?.answer || '',
    ),
    [suggestion, setSuggestion] = useState(''),
    [kind, setKind] = useState('QUESTION'),
    [id, setId] = useState(''),
    [quote, setQuote] = useState(''),
    [source, setSource] = useState(''),
    [severity, setSeverity] = useState('中');
  return (
    <ReviewDialog
      title="从回复添加待确认事项"
      busy={busy}
      onClose={onClose}
      wide
      footer={
        <>
          <button onClick={onClose}>取消</button>
          <button form="reviewManual" disabled={busy} className="primary">
            人工确认添加
          </button>
        </>
      }
    >
      <Form
        id="reviewManual"
        onSubmit={(e) => {
          e.preventDefault();
          void onSave({
            revision: record.revision,
            turn_id: turnId,
            finding: {
              key: crypto.randomUUID(),
              kind,
              title,
              description,
              suggestion,
              severity,
              reason: '人工提取，等级待核对',
              impact: '人工提取，业务影响待核对',
              case_ids: id ? [Number(id)] : [],
              fields: [],
              evidence: quote ? [{ source, quote }] : [],
            },
          });
        }}
      >
        <label className="field-label">
          标题
          <input
            required
            value={title}
            maxLength={500}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <FormSelect
          label="类型"
          value={kind}
          options={Object.entries(reviewKinds).map(([value, label]) => ({
            value,
            label,
            disabled: record.mode === 'QUALITY' && ['MISMATCH', 'MISSING'].includes(value),
          }))}
          onChange={setKind}
        />
        <FormSelect
          label="等级"
          value={severity}
          options={['高', '中', '低'].map((value) => ({ value, label: value }))}
          onChange={setSeverity}
        />
        <label className="field-label">
          说明
          <textarea
            required
            value={description}
            maxLength={10000}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <label className="field-label">
          建议
          <textarea
            required
            value={suggestion}
            maxLength={10000}
            onChange={(e) => setSuggestion(e.target.value)}
          />
        </label>
        <FormSelect
          label="关联固定用例"
          value={id}
          options={[
            { value: '', label: '无现成用例' },
            ...record.input.cases.map((c) => ({
              value: String(c.id),
              label: `${c.number} / v${c.version}`,
            })),
          ]}
          onChange={setId}
        />
        <FormSelect
          label="需求原文来源"
          value={source}
          options={[
            { value: '', label: '不关联原文' },
            ...record.input.materials.map((m) => ({ value: m.source_id, label: m.name })),
          ]}
          onChange={setSource}
        />
        <label className="field-label">
          原文摘录
          <textarea value={quote} maxLength={1000} onChange={(e) => setQuote(e.target.value)} />
        </label>
        {error && <p className="inline-error">{error}</p>}
      </Form>
    </ReviewDialog>
  );
}
