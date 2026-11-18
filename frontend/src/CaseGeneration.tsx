import { CandidateIssueDialog, GenerationCandidateIssues } from './GenerationCandidateIssues';
import type { GenerationCandidateIssue } from './generationPage';
import { AIConfigurationSummary } from './AIConfigurationSummary';
import { callModeName } from './aiConfiguration';
import { AnalysisRecordDelete } from './AnalysisRecordDelete';
import { PageJump } from './PageJump';
import { AcceptancePanel } from './AnalysisAcceptance';
import { GenerationTable } from './GenerationTable';
import { GenerationEvidence } from './GenerationEvidence';
import {
  GenerationBatchReview,
  GenerationDuplicateResolution,
  batchReviewProblem,
} from './GenerationBatchReview';
import type { ReviewItem } from './GenerationReview';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from './Icon';
import { CaseDialog } from './CaseDialog';
import { FormSelect } from './FormSelect';
import { codeError, codeRequest, parseCodeOptions } from './codeAnalysisApi';
import type { CodeOptions } from './codeAnalysisApi';
import { parsePrototypeLibrary } from './prototypeApi';
import type { PrototypeSource } from './prototypeApi';
import { caseError, blankDesign } from './caseApi';
import type { CaseList } from './caseApi';
import type { User } from './Auth';
import type { OverviewTarget } from './OverviewEntry';
import type { Project } from './Projects';
import { CaseGenerationNew } from './CaseGenerationNew';
import {
  GenerationClarification,
  GenerationDetail,
  GenerationImport,
} from './CaseGenerationDialogs';
import {
  currentHandling,
  GENERATION_PAGE_SIZE,
  generationGroups,
  generationRoundRecord,
  generationAdoption,
  generationDuration,
  generationKinds,
  generationMarkdown,
  generationReady,
  generationSelection,
  generationTabs,
} from './generationPage';
import type {
  GenerationDecision,
  GenerationPreviewItem,
  GenerationRecord,
  GenerationSummary,
  GenerationTab,
} from './generationPage';
import { generationCaseSnapshot } from './generationRead';
import { downloadGeneration, generationXlsx } from './generationExport';
import './code-analysis.css';
import './requirement-ui.css';
import './change-analysis.css';
import './case-generation.css';
import {
  generationAction,
  generationApplyPreview,
  generationBase,
  generationError,
  generationFailure,
  generationSummaries,
  generationDetail,
} from './generationApi';
import { GenerationChat } from './GenerationChat';
import { GenerationCliWorkspace } from './GenerationCliWorkspace';
import { GenerationSingleReview, GenerationApplicationResult } from './GenerationReview';

function CachedCliWorkspace(props: Parameters<typeof GenerationCliWorkspace>[0]) {
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (props.open) setOpened(true);
  }, [props.open]);
  return opened || props.open ? <GenerationCliWorkspace {...props} /> : null;
}

type Props = {
  onRecordDeleted?: () => void;
  overviewTarget?: OverviewTarget | null;
  project: Project | null;
  user: User;
  onSessionEnd: () => void;
};
type WorkspaceProps = Props & {
  rows: GenerationRecord[];
  onChange: (rows: GenerationRecord[]) => void;
  hasMore: boolean;
  onMore: () => void;
  summaries?: GenerationSummary[];
  selectedRecordId?: string;
  onSelectRecord?: (id: string) => void;
  detailLoading?: boolean;
};
export function CaseGeneration(props: Props) {
  const [deletionVersion, setDeletionVersion] = useState(0);
  return (
    <GenerationRemote
      key={`${props.user.id}:${props.project?.id}:${deletionVersion}`}
      {...props}
      overviewTarget={deletionVersion ? null : props.overviewTarget}
      onRecordDeleted={() => setDeletionVersion((v) => v + 1)}
    />
  );
}
function GenerationRemote(props: Props) {
  const [rows, setRows] = useState<GenerationRecord[]>([]),
    [summaries, setSummaries] = useState<GenerationSummary[]>([]),
    [selectedId, setSelectedId] = useState(
      props.overviewTarget ? String(props.overviewTarget.id) : '',
    ),
    [hasMore, setHasMore] = useState(false),
    [loaded, setLoaded] = useState(false),
    [detailLoading, setDetailLoading] = useState(false),
    [error, setError] = useState(''),
    [detailError, setDetailError] = useState('');
  const [listPage, setListPage] = useState(1);
  const epoch = useRef(0),
    rowsRef = useRef(rows),
    alive = useRef(true),
    loadedKeys = useRef(new Map<string, string>());
  rowsRef.current = rows;
  useEffect(() => {
    alive.current = true;
    if (!props.project) return;
    const c = new AbortController();
    let fetching = false;
    async function read() {
      if (fetching || c.signal.aborted || !props.project) return;
      fetching = true;
      const e = epoch.current;
      try {
        const results = await Promise.all(
          Array.from({ length: listPage }, (_, n) =>
            generationSummaries(props.project!.id, c.signal, n + 1),
          ),
        );
        if (c.signal.aborted || e !== epoch.current) return;
        const next = results.flatMap((r) => r.items);
        if (props.overviewTarget && !next.some((r) => r.id === String(props.overviewTarget!.id))) {
          const targeted = await generationSummaries(
            props.project!.id,
            c.signal,
            1,
            String(props.overviewTarget.id),
          );
          if (!targeted.items.some((r) => r.id === String(props.overviewTarget!.id)))
            throw Error('generation_not_found');
          next.push(...targeted.items);
        }
        if (c.signal.aborted || e !== epoch.current) return;
        setSummaries(next);
        setSelectedId((id) => (next.some((r) => r.id === id) ? id : next[0]?.id || ''));
        setHasMore(results.at(-1)?.hasMore || false);
        setLoaded(true);
        setError('');
      } catch (e) {
        if (
          !c.signal.aborted &&
          e instanceof Error &&
          ['not_authenticated', 'project_not_found'].includes(e.message)
        ) {
          setRows([]);
          setSummaries([]);
          setLoaded(true);
        }
        if (!c.signal.aborted) setError(generationError(e, props.onSessionEnd));
      } finally {
        fetching = false;
      }
    }
    void read();
    const timer = window.setInterval(() => void read(), 3000);
    return () => {
      c.abort();
      window.clearInterval(timer);
    };
  }, [props.project, props.onSessionEnd, props.overviewTarget, listPage]);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const refreshKey = summaries.find((r) => r.id === selectedId)?.refreshKey;
  useEffect(() => {
    if (!props.project || !selectedId || refreshKey === undefined) return;
    if (loadedKeys.current.get(selectedId) === refreshKey) return;
    const c = new AbortController(),
      e = epoch.current;
    let fetching = false;
    async function readDetail() {
      if (fetching || c.signal.aborted || !props.project) return;
      fetching = true;
      setDetailLoading(!rowsRef.current.some((r) => r.id === selectedId));
      try {
        const next = await generationDetail(props.project.id, selectedId, c.signal);
        if (c.signal.aborted || e !== epoch.current) return;
        loadedKeys.current.set(selectedId, refreshKey!);
        setRows((old) => [
          { ...next, chatDrafts: old.find((r) => r.id === next.id)?.chatDrafts || {} },
          ...old.filter((r) => r.id !== next.id),
        ]);
        setDetailError('');
      } catch (e) {
        if (!c.signal.aborted) setDetailError(generationError(e, props.onSessionEnd));
      } finally {
        fetching = false;
        if (!c.signal.aborted) setDetailLoading(false);
      }
    }
    void readDetail();
    // Retry only reads after a transient failure, never generation/application actions.
    const timer = window.setInterval(() => {
      if (loadedKeys.current.get(selectedId) !== refreshKey) void readDetail();
    }, 3000);
    return () => {
      c.abort();
      window.clearInterval(timer);
    };
  }, [props.project, props.onSessionEnd, selectedId, refreshKey]);
  return (
    <>
      {(error || detailError) && (
        <p className="form-error" role="alert">
          {error || detailError}
        </p>
      )}
      {props.project && !loaded ? (
        <section className="panel empty" aria-busy={!error}>
          {!error && <span className="generation-spinner" aria-hidden="true" />}
          <p role="status">
            {error ? '生成记录读取失败，正在等待重新读取。' : '正在读取生成记录，请稍候…'}
          </p>
        </section>
      ) : (
        <GenerationWorkspace
          {...props}
          rows={rows}
          summaries={summaries}
          selectedRecordId={selectedId}
          detailLoading={detailLoading || (!!selectedId && !rows.some((r) => r.id === selectedId))}
          hasMore={hasMore}
          onMore={() => setListPage((value) => value + 1)}
          onSelectRecord={(id) => {
            setDetailError('');
            setSelectedId(id);
          }}
          onChange={(next) => {
            epoch.current++;
            if (!alive.current) return;
            setRows(next);
            setSummaries((old) => {
              const merged = old.map((summary) => {
                const row = next.find((r) => r.id === summary.id);
                return row
                  ? {
                      ...summary,
                      title: row.title,
                      timings: row.timings,
                      status: row.status || summary.status,
                      serverRevision: row.serverRevision || summary.serverRevision,
                    }
                  : summary;
              });
              for (const row of next)
                if (!merged.some((r) => r.id === row.id)) {
                  merged.unshift({
                    id: row.id,
                    projectId: row.projectId,
                    ownerId: row.ownerId,
                    title: row.title,
                    createdAt: row.createdAt,
                    timings: row.timings,
                    mode: row.mode,
                    status: row.status || 'PREPARED',
                    serverRevision: row.serverRevision || 1,
                    hasMaterials: !!row.materials.length,
                    active: false,
                    refreshKey: '',
                  });
                  loadedKeys.current.set(row.id, '');
                  setSelectedId(row.id);
                }
              return merged;
            });
          }}
        />
      )}
    </>
  );
}
export function GenerationDuration({ timings }: Pick<GenerationRecord, 'timings'>) {
  const [now, setNow] = useState(Date.now());
  const running = timings?.some((t) => t.startedAt && !t.finishedAt);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  return (
    <small title="时:分:秒；累计各批次本次执行，不含排队及历史重试。取消或中断按最后保存进度计算。">
      耗时 {generationDuration(timings, now)}
    </small>
  );
}
export function GenerationActivity({
  record,
  onRetry,
  onRevalidate,
  candidateBase,
  busy = false,
}: {
  record: Pick<GenerationRecord, 'batches'>;
  onRetry?: (id: number) => void;
  onRevalidate?: (id: number) => void;
  candidateBase?: string;
  busy?: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  const active = record.batches.some((b) => ['QUEUED', 'RUNNING'].includes(b.status));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  const phases: Record<string, string> = {
    cli_native_running: '原生CLI执行中',
    preparing: '准备调用资料',
    request_sent: '连接AI，等待响应',
    connected: '已连接，等待AI输出',
    receiving: '正在接收AI响应',
    validating_response: '正在校验AI响应',
    validating_report: '正在校验并保存候选',
    completed: '候选已保存',
    cli_starting: '正在启动CLI',
    cli_waiting: 'CLI已启动，等待模型结果',
    cli_reasoning: 'CLI正在推理',
    cli_reading: 'CLI正在读取固定资料',
    cli_failed: 'CLI执行失败',
  };
  const categories: Record<string, string> = {
    context_limit: '上下文容量超限',
    output_limit: '输出容量超限',
    timeout: '上游超时',
    quota: '额度不足',
    rate_limit: '请求限流',
    authentication: '认证失败',
    model_unavailable: '模型不可用',
    overloaded: '服务繁忙',
    connection: '连接异常',
    parameters: '参数被拒绝',
    unknown: '供应商未提供可识别原因',
  };
  return (
    <div className="generation-activity-list">
      {record.batches
        .filter((b) => ['QUEUED', 'RUNNING', 'FAILED'].includes(b.status))
        .map((b) => {
          const d = b.diagnostics || {},
            running = b.status === 'RUNNING',
            waiting = b.status === 'QUEUED';
          const elapsed = b.startedAt
            ? Math.max(0, Math.floor((now - Date.parse(b.startedAt)) / 1000))
            : null;
          return (
            <section
              className="generation-activity evidence"
              key={b.key}
              aria-busy={running || waiting}
            >
              <div className="row">
                {(running || waiting) && <span className="generation-spinner" aria-hidden="true" />}
                <strong role="status">
                  {waiting
                    ? '排队中 · 等待后台开始'
                    : running
                      ? `正在生成 · ${phases[String(d.phase)] || '等待AI完成'}`
                      : b.candidateAvailable
                        ? 'AI已返回 · 候选待核对'
                        : record.batches.some((v) => v.nativeResultId)
                          ? '早期生成未完成 · 已保存对话候选'
                          : '生成失败'}
                </strong>
                {running && elapsed !== null && (
                  <span className="hint">
                    已运行 {Math.floor(elapsed / 60)}分{elapsed % 60}秒
                  </span>
                )}
              </div>
              {(running || waiting) && <p className="hint">任务在后台继续，可离开页面。</p>}
              {typeof d.received_bytes === 'number' && (
                <p className="hint">
                  {d.call_mode === 'CODEX_EXEC' ? 'CLI事件已接收' : '已接收'}{' '}
                  {d.received_bytes.toLocaleString()} 字节 · 输出文字{' '}
                  {Number(d.output_characters || 0).toLocaleString()} 字符
                </p>
              )}
              {b.status === 'FAILED' && (
                <p className="form-error">
                  {b.candidateAvailable
                    ? '原始响应已保存，结果校验未通过；可查看候选并免费重新校验'
                    : categories[String(d.error_category)] || '调用失败，未保存详细上游原因'}{' '}
                  · {generationFailure(b.reason)}
                </p>
              )}
              {b.status === 'FAILED' && b.candidateAvailable && b.id && (
                <div className="row">
                  {candidateBase && (
                    <a className="button-link small" href={`${candidateBase}/${b.id}/candidate`}>
                      下载原始候选
                    </a>
                  )}
                  {onRevalidate && (
                    <button className="small" disabled={busy} onClick={() => onRevalidate(b.id!)}>
                      重新校验（不调用AI）
                    </button>
                  )}
                </div>
              )}
              {b.status === 'FAILED' && !b.nativeResultId && onRetry && b.id && (
                <button className="small" disabled={busy} onClick={() => onRetry(b.id!)}>
                  人工重试（使用本人AI，可能计费）
                </button>
              )}
              {Object.keys(d).length > 0 && (
                <details>
                  <summary>调用诊断</summary>
                  <dl>
                    {[
                      ['请求ID', d.request_id],
                      ['响应ID', d.response_id],
                      ['HTTP状态', d.upstream_http_status || d.http_status],
                      ['供应商错误代码', d.upstream_code],
                      ['供应商错误类型', d.upstream_type],
                      ['结束事件', d.termination],
                      ['调用耗时（秒）', d.elapsed_seconds],
                      ['供应商报告超时（秒）', d.reported_timeout_seconds],
                    ]
                      .filter(([, value]) => value !== undefined)
                      .map(([label, value]) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd className="mono">{value}</dd>
                        </div>
                      ))}
                  </dl>
                </details>
              )}
            </section>
          );
        })}
    </div>
  );
}
function generationGaps(record: Pick<GenerationRecord, 'rawReports'>, includeBusiness = false) {
  return (record.rawReports || []).flatMap((report, batch) => {
    if (report.contract_version === 3) {
      const output = report.model_output;
      if (
        !output ||
        typeof output !== 'object' ||
        !('notes' in output) ||
        !Array.isArray(output.notes)
      )
        return [];
      return output.notes.flatMap((note: unknown, index: number) => {
        if (
          !note ||
          typeof note !== 'object' ||
          !('kind' in note) ||
          !(
            includeBusiness
              ? ['BUSINESS_QUESTION', 'EXECUTION_SETUP', 'UNFINISHED']
              : ['EXECUTION_SETUP', 'UNFINISHED']
          ).includes(String(note.kind)) ||
          !('text' in note) ||
          typeof note.text !== 'string' ||
          !note.text.trim()
        )
          return [];
        return [
          {
            id: `${batch}-${index}`,
            kind: String(note.kind),
            reason: note.text,
            next: '',
            scope:
              'sources' in note && Array.isArray(note.sources)
                ? note.sources.filter((x: unknown) => typeof x === 'string').join('、')
                : '',
          },
        ];
      });
    }
    if (!Array.isArray(report.discovery_gaps)) return [];
    return report.discovery_gaps.flatMap((gap, index) => {
      if (
        !gap ||
        typeof gap !== 'object' ||
        typeof gap.reason !== 'string' ||
        typeof gap.next_step !== 'string'
      )
        return [];
      return [
        {
          id: `${batch}-${index}`,
          kind: String(gap.kind),
          reason: gap.reason,
          next: gap.next_step,
          scope: Array.isArray(gap.scenario_refs)
            ? gap.scenario_refs.filter((x: unknown) => typeof x === 'string').join('、')
            : '',
        },
      ];
    });
  });
}
export function GenerationGaps({
  record,
  includeBusiness = false,
}: {
  record: Pick<GenerationRecord, 'rawReports'>;
  includeBusiness?: boolean;
}) {
  const gaps = generationGaps(record, includeBusiness);
  if (!gaps.length) return null;
  return (
    <section className="panel-pad">
      <h3>{includeBusiness ? '简短说明与待处理范围' : '执行准备与未覆盖范围'}</h3>
      <p className="hint">执行前请补齐准备事项。</p>
      {gaps.map((gap) => (
        <article className="evidence" key={gap.id}>
          <span className="badge orange">
            {gap.kind === 'EXECUTION_SETUP'
              ? '执行准备待补'
              : gap.kind === 'BUSINESS_QUESTION'
                ? '业务待澄清'
                : gap.kind === 'UNFINISHED'
                  ? '未完成范围'
                  : gap.kind === 'UNREAD_CONTENT'
                    ? '资料读取缺口'
                    : '分析未完成 / 待核对'}
          </span>
          <p>{gap.reason}</p>
          {gap.scope && <p className="hint">{gap.scope}</p>}
          {gap.next && <p>下一步：{gap.next}</p>}
        </article>
      ))}
    </section>
  );
}
export function GenerationReportDetails({
  report,
  index,
}: {
  report: Record<string, unknown>;
  index: number;
}) {
  const output = report.model_output;
  const compact = report.contract_version === 3 && output !== null && typeof output === 'object';
  return (
    <section className="evidence">
      {compact && (
        <p>
          用例结果 {index + 1} ·{' '}
          {'cases' in output && Array.isArray(output.cases) ? output.cases.length : 0} 条建议
          {'notes' in output && Array.isArray(output.notes) && output.notes.length > 0
            ? ` · ${output.notes.length} 条简短说明`
            : ''}
          {'complete' in output && typeof output.complete === 'boolean'
            ? output.complete
              ? ' · AI声明范围已完成，仍需人工审核'
              : ' · AI声明范围未完成'
            : ''}
        </p>
      )}
      <details>
        <summary>
          {compact ? '原始用例结果与简短说明' : '完整本批规则、分支、场景及覆盖依据'} · {index + 1}
        </summary>
        <pre className="mono">{JSON.stringify(report, null, 2)}</pre>
      </details>
    </section>
  );
}
function state(r: GenerationRecord | GenerationSummary) {
  if ('refreshKey' in r)
    return (
      {
        PREPARED: '待开始生成',
        QUEUED: '排队中',
        RUNNING: '生成中',
        COMPLETED: '生成已完成 · 查看报告',
        FAILED: '失败 · 可人工重试',
        CANCELLED: '已取消',
      } as Record<string, string>
    )[r.status];
  if (r.status === 'FAILED' && r.batches.some((b) => b.candidateAvailable))
    return 'AI已返回 · 待校验处理';
  if (r.origin === 'SERVER')
    return (
      (
        {
          PREPARED: '待开始生成',
          QUEUED: '排队中',
          RUNNING: '生成中',
          COMPLETED:
            r.outcome === 'PARTIAL'
              ? '部分完成 · 有待补或未覆盖范围'
              : r.outcome === 'BLOCKED'
                ? '生成受阻 · 需核对依据'
                : '声明范围生成完成',
          FAILED: '失败 · 可人工重试',
          CANCELLED: '已取消',
        } as Record<string, string>
      )[r.status || ''] || r.status
    );
  return r.cancelled
    ? '范围已取消 · 本页'
    : r.origin === 'DRAFT'
      ? '待接入 · 范围草稿'
      : '本页导入预览 · 待正式校验';
}
function GenerationScope({ record }: { record: GenerationRecord | null }) {
  return (
    <aside className="panel code-analysis-scope">
      <h2>固定依据与范围</h2>
      <div className="panel-pad">
        {record ? (
          <>
            <p className="hint">{record.scope}</p>
            {record.materials.map((m) => (
              <section className="evidence" key={`${m.sourceId}:${m.side || m.before}`}>
                <strong>{m.name}</strong>
                <p className="hint">
                  {['OLD', 'BEFORE'].includes(m.side || '')
                    ? '旧基准'
                    : m.before
                      ? '新目标'
                      : m.side === 'SUPPLEMENT'
                        ? '增量补充'
                        : '当前依据'}{' '}
                  · {m.versionName || m.version || '未固定'}
                </p>
                {m.before && <p className="hint">旧基准：{m.beforeName || m.before}</p>}
                {m.update && <p>{m.update}</p>}
                <p className="hint">
                  {m.readState === 'NOT_LOADED'
                    ? '正文尚未读取'
                    : `${m.readState} · ${m.segments.length}个固定片段`}
                </p>
                {!!m.paths.length && (
                  <details>
                    <summary>所选文件/页面 · {m.paths.length}项</summary>
                    {m.paths.map((p) => (
                      <p className="hint mono" key={p}>
                        {p}
                      </p>
                    ))}
                  </details>
                )}
              </section>
            ))}
            <p className="hint">{record.caseScope}</p>
            <div className="evidence">
              {record.baselineId ? '已固定历史基准' : '无历史生成基准'}
            </div>
            {record.decisions.map((d) => (
              <section className="evidence" key={d.key}>
                <strong>已确认结论 · {d.key}</strong>
                <p>{d.conclusion}</p>
                <p className="hint">
                  {d.basis}
                  <br />
                  {d.actor} · {new Date(d.time).toLocaleString()}
                </p>
              </section>
            ))}
            {record.limitations.map((l, i) => (
              <p className="hint" key={i}>
                {l}
              </p>
            ))}
          </>
        ) : (
          <p className="hint">选择记录后显示资料版本、用例范围及证据。</p>
        )}
      </div>
    </aside>
  );
}
export function GenerationWorkspace({
  overviewTarget,
  onRecordDeleted,
  project,
  user,
  rows,
  onChange,
  onSessionEnd,
  hasMore,
  onMore,
  summaries,
  selectedRecordId,
  onSelectRecord,
  detailLoading = false,
}: WorkspaceProps) {
  const [selected, setSelected] = useState(''),
    [tab, setTab] = useState<GenerationTab>(
      overviewTarget?.group === 'questions' ? 'questions' : 'suggestions',
    ),
    [query, setQuery] = useState(''),
    [kind, setKind] = useState(''),
    [handling, setHandling] = useState(''),
    [feature, setFeature] = useState(''),
    [page, setPage] = useState(1),
    [chosen, setChosen] = useState<string[]>([]),
    [detail, setDetail] = useState(''),
    [detailKeys, setDetailKeys] = useState<string[]>([]),
    [detailRefresh, setDetailRefresh] = useState(0),
    [previewReturnKey, setPreviewReturnKey] = useState(''),
    [clarify, setClarify] = useState(''),
    [chat, setChat] = useState(false),
    [chatDraftTurn, setChatDraftTurn] = useState<number | null>(null),
    [chatFunction, setChatFunction] = useState('整体'),
    [reference, setReference] = useState(''),
    [newOpen, setNewOpen] = useState(false),
    [importOpen, setImportOpen] = useState(false),
    [exportOpen, setExportOpen] = useState(false),
    [exportIds, setExportIds] = useState<string[]>([]),
    [failuresOpen, setFailuresOpen] = useState(false),
    [notice, setNotice] = useState(''),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false),
    [options, setOptions] = useState<CodeOptions | null>(null),
    [prototypes, setPrototypes] = useState<PrototypeSource[]>([]),
    [snapshot, setSnapshot] = useState<CaseList | null>(null),
    [preview, setPreview] = useState<{
      items: GenerationPreviewItem[];
      revision: number;
      keys: string[];
      single: boolean;
    } | null>(null),
    [reviewApplicationId, setReviewApplicationId] = useState<number | null>(null),
    [historyOpen, setHistoryOpen] = useState(true),
    [scopeKey, setScopeKey] = useState<string | null>(null),
    [textQuery, setTextQuery] = useState(''),
    [reviewChecks, setReviewChecks] = useState<GenerationPreviewItem[]>([]),
    [reviewChoices, setReviewChoices] = useState<Record<string, ReviewItem>>({}),
    [resolveKey, setResolveKey] = useState('');
  const [nativeRoundId, setNativeRoundId] = useState<string | null>(null);
  const [candidateIssue, setCandidateIssue] = useState<GenerationCandidateIssue | null>(null);
  const scopeTrigger = useRef<HTMLElement | null>(null),
    scopeToggle = useRef<HTMLButtonElement>(null),
    previewTrigger = useRef<HTMLElement | null>(null),
    hadPreview = useRef(false),
    previewScroll = useRef<{ top: number; left: number; viewportTop: number } | null>(null);
  const controller = useRef<AbortController | null>(null),
    generation = useRef(0),
    alive = useRef(true),
    rowsRef = useRef(rows);
  rowsRef.current = rows;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      controller.current?.abort();
    };
  }, []);
  const record =
      selectedRecordId !== undefined
        ? rows.find((r) => r.id === selectedRecordId) || null
        : rows.find((r) => r.id === selected) || rows[0] || null,
    ready =
      record?.origin === 'SERVER' &&
      record.suggestions.length +
        record.questions.length +
        (record.rawReports?.length || 0) +
        (record.candidateIssues?.length || 0) >
        0,
    adoption = record ? generationAdoption(record) : null,
    item = record?.suggestions.find((s) => s.key === detail),
    detailApplication = record?.applications?.find(
      (application) =>
        ['QUEUED', 'RUNNING'].includes(application.status) &&
        application.items.some(
          (i) => i.key === detail && ['PENDING', 'RUNNING'].includes(String(i.status)),
        ),
    );
  const nativeRound = nativeRoundId ?? record?.nativeRounds?.[0]?.id ?? '';
  const roundRecord = generationRoundRecord(record, nativeRound);
  useEffect(() => {
    setNativeRoundId(null);
  }, [record?.id]);
  useEffect(() => {
    if (nativeRoundId === null && record?.nativeRounds?.length)
      setNativeRoundId(record.nativeRounds[0].id);
  }, [nativeRoundId, record?.nativeRounds]);
  useEffect(() => {
    setChosen([]);
    setFeature('');
    setKind('');
    setHandling('');
    setTextQuery('');
    setPage(1);
    setDetail('');
  }, [nativeRound]);
  useEffect(() => {
    setTextQuery('');
    setChosen([]);
    setPage(1);
    setReviewChecks([]);
    setReviewChoices({});
    setResolveKey('');
    setCandidateIssue(null);
    setScopeKey(null);
    setPreview(null);
    setPreviewReturnKey('');
  }, [record?.id]);
  useEffect(() => {
    if (scopeKey === null) return;
    const trigger = scopeTrigger.current,
      fallback = scopeToggle.current;
    document.getElementById('generation-scope-close')?.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (
        event.key === 'Escape' &&
        !event.defaultPrevented &&
        !document.querySelector('dialog[open], [popover]:popover-open')
      ) {
        event.preventDefault();
        setScopeKey(null);
      }
    };
    document.addEventListener('keydown', keydown);
    return () => {
      document.removeEventListener('keydown', keydown);
      const target = trigger?.isConnected ? trigger : fallback;
      target?.focus({ preventScroll: true });
    };
  }, [scopeKey]);
  useEffect(() => {
    if (!preview && !loading && hadPreview.current && typeof document !== 'undefined') {
      const area = document.querySelector<HTMLElement>('.generation-page .cg-table-scroll'),
        position = previewScroll.current;
      if (area && position) {
        area.scrollTop = position.top;
        area.scrollLeft = position.left;
        window.scrollBy(0, area.getBoundingClientRect().top - position.viewportTop);
      }
      if (!detail) {
        const target = previewTrigger.current?.isConnected
          ? previewTrigger.current
          : document.querySelector<HTMLElement>('.generation-page .generation-bulk button');
        target?.focus({ preventScroll: true });
      }
      previewScroll.current = null;
      hadPreview.current = false;
    }
    if (preview) hadPreview.current = true;
  }, [preview, loading, detail]);
  async function persist(path: string, body?: unknown) {
    if (!project || loading) return;
    controller.current?.abort();
    const c = new AbortController(),
      g = ++generation.current;
    controller.current = c;
    setLoading(true);
    setError('');
    try {
      const next = await generationAction(project.id, path, body, c.signal);
      if (!alive.current || c.signal.aborted || g !== generation.current) return;
      const existing = rowsRef.current.find((r) => r.id === next.id);
      onChange(
        existing
          ? rowsRef.current.map((r) =>
              r.id === next.id ? { ...next, chatDrafts: r.chatDrafts } : r,
            )
          : [next, ...rowsRef.current],
      );
      setSelected(next.id);
      setNewOpen(false);
      setImportOpen(false);
      if (
        (path.endsWith('/start') || path.endsWith('/retry')) &&
        next.batches.some((b) => b.terminalAvailable)
      ) {
        setChat(true);
        setChatFunction('整体');
        setReference('');
      }
      return next;
    } catch (e) {
      if (!c.signal.aborted && alive.current) setError(generationError(e, onSessionEnd));
    } finally {
      if (!c.signal.aborted && alive.current && g === generation.current) setLoading(false);
    }
  }
  function choose(id: string) {
    generation.current++;
    controller.current?.abort();
    setLoading(false);
    setSelected(id);
    onSelectRecord?.(id);
    setPage(1);
    setTab('suggestions');
    setChosen([]);
    setKind('');
    setHandling('');
    setFeature('');
    setTextQuery('');
    setScopeKey(null);
    setReviewChecks([]);
    setReviewChoices({});
    setResolveKey('');
    setPreview(null);
    setReviewApplicationId(null);
    setDetail('');
    setClarify('');
    setError('');
    setReference('');
    setChatFunction('整体');
  }
  async function exportRecords() {
    if (!project || loading || !exportIds.length) return;
    controller.current?.abort();
    const c = new AbortController(),
      g = ++generation.current;
    controller.current = c;
    setLoading(true);
    setError('');
    try {
      const full = await Promise.all(
        exportIds.map((id) => generationDetail(project.id, id, c.signal)),
      );
      if (!alive.current || c.signal.aborted || g !== generation.current) return;
      downloadGeneration('用例生成_完整报告.md', full.map(generationMarkdown).join('\n\n---\n\n'));
      setExportOpen(false);
    } catch (e) {
      if (!c.signal.aborted && alive.current) setError(generationError(e, onSessionEnd));
    } finally {
      if (!c.signal.aborted && alive.current && g === generation.current) setLoading(false);
    }
  }
  async function newRecord() {
    if (!project || loading) return;
    controller.current?.abort();
    const c = new AbortController(),
      g = ++generation.current;
    controller.current = c;
    setLoading(true);
    setError('');
    try {
      const results = await Promise.allSettled([
        codeRequest(`/api/projects/${project.id}/code-analysis/options`, parseCodeOptions, {
          signal: c.signal,
        }),
        codeRequest(`/api/projects/${project.id}/prototypes`, parsePrototypeLibrary, {
          signal: c.signal,
        }),
        generationCaseSnapshot(project.id, c.signal),
      ]);
      if (!alive.current || c.signal.aborted || g !== generation.current) return;
      for (const r of results) if (r.status === 'rejected') throw r.reason;
      const [a, b, s] = results;
      if (a.status === 'fulfilled' && b.status === 'fulfilled' && s.status === 'fulfilled') {
        setOptions(a.value);
        setPrototypes(b.value.sources);
        setSnapshot(s.value);
        setNewOpen(true);
      }
    } catch (e) {
      if (alive.current && !c.signal.aborted && g === generation.current)
        setError(codeError(e, onSessionEnd));
    } finally {
      if (alive.current && !c.signal.aborted && g === generation.current) setLoading(false);
    }
  }
  function closePreview() {
    setPreview(null);
    setPreviewReturnKey('');
  }
  async function applicationPreview(
    keys = chosen,
    source = record,
    refresh = false,
    single = false,
  ) {
    if (!project || !source || !keys.length || loading) return false;
    if (!refresh && typeof document !== 'undefined') {
      previewTrigger.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const area = document.querySelector<HTMLElement>('.generation-page .cg-table-scroll');
      previewScroll.current = area
        ? {
            top: area.scrollTop,
            left: area.scrollLeft,
            viewportTop: area.getBoundingClientRect().top,
          }
        : null;
    }
    controller.current?.abort();
    const c = new AbortController(),
      g = ++generation.current,
      target = source.id,
      requested = [...keys];
    controller.current = c;
    setLoading(true);
    setError('');
    try {
      const [next, serverPreview] = await Promise.all([
        generationCaseSnapshot(project.id, c.signal),
        generationApplyPreview(project.id, source.id, requested, c.signal),
      ]);
      if (!alive.current || c.signal.aborted || g !== generation.current) return false;
      const r = rowsRef.current.find((r) => r.id === target);
      if (!r) throw Error('记录已变化，请重新选择。');
      const items = serverPreview.items;
      setSnapshot(next);
      if (!refresh)
        setPreviewReturnKey(requested.length === 1 && detail === requested[0] ? detail : '');
      setReviewChecks(items);
      setPreview({
        items,
        revision: next.revision,
        keys: requested,
        single: requested.length === 1 && (single || detail === requested[0]),
      });
      return true;
    } catch (e) {
      if (alive.current && !c.signal.aborted) setError(caseError(e, onSessionEnd));
      return false;
    } finally {
      if (alive.current && !c.signal.aborted && g === generation.current) setLoading(false);
    }
  }
  async function openDetail(key: string) {
    if (!project || loading) return;
    controller.current?.abort();
    const c = new AbortController(),
      g = ++generation.current;
    controller.current = c;
    setLoading(true);
    setError('');
    try {
      const value = await generationCaseSnapshot(project.id, c.signal, true);
      if (alive.current && !c.signal.aborted && g === generation.current) {
        setSnapshot(value);
        setDetailKeys(
          (filtered.some((s) => s.key === key) ? filtered : record?.suggestions || []).map(
            (s) => s.key,
          ),
        );
        setDetail(key);
      }
    } catch (e) {
      if (alive.current && !c.signal.aborted) setError(generationError(e, onSessionEnd));
    } finally {
      if (alive.current && !c.signal.aborted && g === generation.current) setLoading(false);
    }
  }
  function ask(key: string, func: string) {
    setReference(key);
    setChatFunction(func || '整体');
    setChat(true);
    setDetail('');
  }
  function supplement(d: GenerationDecision) {
    if (!record) return;
    void persist(`/${record.id}/supplement`, {
      request_id: crypto.randomUUID(),
      revision: record.serverRevision,
      decision_key: d.key,
    });
  }
  const detailIndex = detailKeys.indexOf(detail);
  const nextDetailKey = detailKeys
    .slice(detailIndex + 1)
    .find((key) => record?.suggestions.some((s) => s.key === key));
  const previousDetailKey = detailKeys
    .slice(0, Math.max(0, detailIndex))
    .reverse()
    .find((key) => record?.suggestions.some((s) => s.key === key));
  function previousDetail() {
    if (!previousDetailKey || loading) return;
    setError('');
    setPage(Math.floor(detailKeys.indexOf(previousDetailKey) / GENERATION_PAGE_SIZE) + 1);
    setDetail(previousDetailKey);
  }
  function nextDetail() {
    if (!nextDetailKey || loading) return;
    setError('');
    setPage(Math.floor(detailKeys.indexOf(nextDetailKey) / GENERATION_PAGE_SIZE) + 1);
    setDetail(nextDetailKey);
  }
  const matching = (roundRecord?.suggestions || []).filter(
      (s) =>
        (!kind || s.kind === kind) &&
        (!handling || (currentHandling(record!, s)?.status || '待审阅') === handling) &&
        (!feature || s.function === feature) &&
        (!textQuery.trim() ||
          [s.key, s.function, ...Object.values(currentHandling(record!, s)?.draft || s.design)]
            .join(' ')
            .toLowerCase()
            .includes(textQuery.trim().toLowerCase())) &&
        (!overviewTarget?.state ||
          record?.id !== String(overviewTarget.id) ||
          overviewTarget.group !== 'suggestions' ||
          !['已应用', '已复用', '已忽略'].includes(
            currentHandling(record!, s)?.status || '待审阅',
          )),
    ),
    filtered = [...generationGroups(matching).values()].flat(),
    pages = Math.max(1, Math.ceil(filtered.length / GENERATION_PAGE_SIZE)),
    currentPage = Math.min(page, pages),
    visible = filtered.slice(
      (currentPage - 1) * GENERATION_PAGE_SIZE,
      currentPage * GENERATION_PAGE_SIZE,
    );
  const nativeChat = !!record?.batches.some((batch) => batch.terminalAvailable);
  const historyTrigger = useRef<HTMLButtonElement>(null);
  const wasChat = useRef(false);
  useEffect(() => {
    if (!chat && wasChat.current) historyTrigger.current?.focus();
    wasChat.current = chat;
  }, [chat]);
  const scopedQuestions =
    !!overviewTarget?.state &&
    record?.id === String(overviewTarget.id) &&
    overviewTarget.group === 'questions';
  const failed = record?.failures || [],
    questionEntries = (roundRecord?.questions || []).filter(
      (q) =>
        !overviewTarget?.state ||
        record?.id !== String(overviewTarget.id) ||
        overviewTarget.group !== 'questions' ||
        !record.decisions.some((d) => d.questionKey === q.key),
    );
  const checked = reviewChecks.filter((i) => {
      const s = record?.suggestions.find((s) => s.key === i.key);
      return s && i.revision === (currentHandling(record!, s)?.revision || 0);
    }),
    issues = Object.fromEntries(
      checked.map((i) => [i.key, batchReviewProblem(i, reviewChoices[i.key])]),
    ),
    duplicateItem = checked.find((i) => i.key === resolveKey),
    evidenceItem = record?.suggestions.find((s) => s.key === scopeKey);
  function resolveIssue(key: string) {
    const check = checked.find((i) => i.key === key);
    if (check?.matches.length && !check.problem) setResolveKey(key);
    else void openDetail(key);
  }
  function submitReview(items: ReviewItem[]) {
    if (!record) return;
    const currentRecord = rowsRef.current.find((r) => r.id === record.id);
    if (
      items.some((item) => {
        const suggestion = currentRecord?.suggestions.find((s) => s.key === item.key),
          current =
            suggestion && currentRecord ? currentHandling(currentRecord, suggestion) : undefined;
        return (
          !suggestion ||
          item.draft_revision !== (current?.revision || 0) ||
          ['已应用', '已复用', '已忽略'].includes(current?.status || '')
        );
      })
    ) {
      setError('候选或草稿已变化，请关闭确认窗后重新核对。');
      return;
    }
    const requestId = crypto.randomUUID();
    void persist(`/${record.id}/applications`, {
      request_id: requestId,
      confirmed: true,
      items,
    }).then((next) => {
      if (!next) return;
      const result = next.applications?.find((a) => a.requestId === requestId),
        successful =
          result?.items.filter((i) => i.status === 'COMPLETED' && i.action !== 'ignore').length ||
          0,
        failures = result?.items.filter((i) => i.status === 'FAILED').length || 0,
        ignored =
          result?.items.filter((i) => i.status === 'COMPLETED' && i.action === 'ignore').length ||
          0;
      setPreview(null);
      if (previewReturnKey) setDetailRefresh((v) => v + 1);
      setPreviewReturnKey('');
      setChosen([]);
      setNotice(
        result?.status === 'COMPLETED'
          ? `本次入库成功 ${successful} 条，失败 ${failures} 条${ignored ? `，忽略 ${ignored} 条` : ''}；成功项已保存，失败项可人工核对。`
          : '本次入库未完成，已成功的用例保留；请核对结果后处理剩余用例。',
      );
    });
  }
  const recordChoices = summaries || rows;
  const nav = (
    <aside
      id="generation-records"
      hidden={!chat && !historyOpen}
      className="panel code-analysis-records"
    >
      <div className="panel-head">
        <h2>{chat ? '历史对话' : '生成记录'}</h2>
      </div>
      <label className="form-field change-record-search">
        搜索记录
        <input
          type="search"
          placeholder="名称或模式"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {recordChoices
        .filter((r) =>
          (r.title + (r.mode === 'INITIAL' ? '首次生成' : '用例维护'))
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .map((r) => (
          <div className="analysis-record-row" key={r.id}>
            <button
              className={`code-record ${r.id === (selectedRecordId ?? record?.id) ? 'active' : ''}`}
              aria-current={r.id === (selectedRecordId ?? record?.id) ? 'true' : undefined}
              onClick={() => choose(r.id)}
            >
              <strong>{r.title}</strong>
              <small>
                {r.mode === 'INITIAL' ? '首次生成' : '用例维护'} ·{' '}
                {state(
                  rows.find(
                    (row) =>
                      row.id === r.id &&
                      row.status === r.status &&
                      row.serverRevision === r.serverRevision,
                  ) || r,
                )}
              </small>
              <small>{new Date(r.createdAt).toLocaleString()}</small>
              <GenerationDuration timings={r.timings} />
            </button>
            {project && (
              <AnalysisRecordDelete
                base={generationBase(project.id)}
                id={r.id}
                projectId={project.id}
                iconOnly
                recordTitle={r.title}
                canDelete={
                  user.platform_role === 'ADMIN' || project.can_manage || r.ownerId === user.id
                }
                refreshKey={`${r.status}:${r.serverRevision}`}
                onDeleted={onRecordDeleted}
                onSessionEnd={onSessionEnd}
              />
            )}
          </div>
        ))}
      {!recordChoices.length && <p className="hint panel-pad">暂无生成记录。</p>}
      {chat && record && (
        <>
          <div className="divider" />
          {[
            '整体',
            ...new Set(
              [
                ...record.suggestions.map((s) => s.function),
                ...record.questions.map((q) => q.function),
              ].filter(Boolean),
            ),
          ].map((f) => (
            <button
              className={`code-record ${chatFunction === f ? 'active' : ''}`}
              key={f}
              onClick={() => {
                setChatFunction(f);
                setReference('');
              }}
            >
              {f}
            </button>
          ))}
        </>
      )}
      {hasMore && (
        <button className="small panel-pad" onClick={onMore}>
          加载更多记录
        </button>
      )}
    </aside>
  );
  function card(s: GenerationRecord['suggestions'][number]) {
    const h = record ? currentHandling(record, s) : undefined,
      d = h?.draft || s.design;
    return (
      <article className="code-finding" key={s.key}>
        <div className="between">
          <div className="row">
            <span className={`badge ${s.kind === 'RETIRE' ? 'orange' : 'green'}`}>
              {generationKinds[s.kind]}
            </span>
            <span className="badge">{h?.status || '待审阅'}</span>
            {s.blocked && !h?.resolved && <span className="badge orange">待人工核对</span>}
          </div>
          <label className="check-label">
            <input
              type="checkbox"
              aria-label={`选择建议 ${s.key}`}
              checked={chosen.includes(s.key)}
              disabled={!record || !generationReady(record, s)}
              onChange={(e) =>
                setChosen((keys) =>
                  e.target.checked ? [...keys, s.key] : keys.filter((k) => k !== s.key),
                )
              }
            />
            选择
          </label>
        </div>
        <h3>
          {s.key} · {d.title}
        </h3>
        <p>{s.reason}</p>
        <div className="code-finding-chain">
          <span>{s.function}</span>
          <span>
            {s.caseId
              ? `内部ID ${s.caseId} / v${s.baseVersion}`
              : '新增编号由平台分配；同场景优先复用'}
          </span>
        </div>
        <p>{d.expected}</p>
        {failed
          .filter((f) => f.key === s.key)
          .map((f, i) => (
            <p className="generation-failure" key={i}>
              应用需核对：{f.reason}
            </p>
          ))}
        <div className="row">
          <button className="small" onClick={() => void openDetail(s.key)}>
            查看与修订
          </button>
          <button className="ghost small" onClick={() => ask(s.key, s.function)}>
            引用提问
          </button>
        </div>
      </article>
    );
  }
  return (
    <div className="code-analysis-page requirement-ui change-analysis-page generation-page">
      <header className="page-head">
        <div>
          <h1>{chat ? '用例生成对话' : '用例生成'}</h1>
          {!chat && <p>查看候选、处理问题并审核入库</p>}
        </div>
        <div className="head-actions">
          {chat ? (
            <button onClick={() => setChat(false)}>返回生成报告</button>
          ) : (
            <>
              <button
                className="primary"
                disabled={!project || loading}
                onClick={() => void newRecord()}
              >
                <Icon name="plus" />
                {loading ? '读取来源中…' : '新建用例生成'}
              </button>
              <button disabled={!project} onClick={() => setImportOpen(true)}>
                导入生成结果
              </button>
              {record?.canCancel && (
                <button disabled={loading} onClick={() => void persist(`/${record.id}/cancel`)}>
                  取消生成
                </button>
              )}
              <button ref={historyTrigger} disabled={!project} onClick={() => setChat(true)}>
                历史对话
              </button>
              <Link className="button-link" to="/cases">
                打开用例管理
              </Link>
            </>
          )}
        </div>
      </header>
      {(error || notice) && (
        <p className={error ? 'form-error' : 'notice'} role={error ? 'alert' : 'status'}>
          {error || notice}
        </p>
      )}
      {!project ? (
        <div className="panel empty">
          <h2>请先选择项目</h2>
        </div>
      ) : (
        <>
          {!chat && !!record?.candidateIssues?.some((issue) => issue.status === 'PENDING') && (
            <div className="notice row" role="status">
              <span>
                {record.candidateIssues.filter((issue) => issue.status === 'PENDING').length}
                项候选存在格式或校验问题，原文已保留；其他有效建议可继续审核。
              </span>
              <button
                className="small"
                onClick={() => {
                  setTab('questions');
                }}
              >
                查看冲突与待澄清
              </button>
            </div>
          )}
          {!chat && record?.origin === 'SERVER' && (
            <GenerationActivity
              record={record}
              busy={loading}
              candidateBase={`${generationBase(project.id)}/${record.id}/batches`}
              onRevalidate={(id) => void persist(`/${record.id}/batches/${id}/revalidate`)}
              onRetry={(id) =>
                void persist(`/${record.id}/batches/${id}/retry`, {
                  request_id: crypto.randomUUID(),
                })
              }
            />
          )}
          {!chat && (
            <section className="code-analysis-overview">
              <div>
                <div className="eyebrow">CASE GENERATION / v0.2</div>
                <h2>{record?.title || '从固定依据开始'}</h2>
                <p>
                  <AIConfigurationSummary value={record?.ai_config} />
                </p>

                <p className="hint">{record ? state(record) : '暂无生成结果'}</p>
              </div>
              <div className="code-analysis-stats">
                {[
                  [
                    '待审阅',
                    ready
                      ? record!.suggestions.filter(
                          (s) => (currentHandling(record!, s)?.status || '待审阅') === '待审阅',
                        ).length
                      : '—',
                  ],
                  [
                    '应用/复用',
                    ready
                      ? record!.suggestions.filter((s) =>
                          ['已应用', '已复用'].includes(currentHandling(record!, s)?.status || ''),
                        ).length
                      : '—',
                  ],
                  ['需人工确认', ready ? failed.length : '—'],
                ].map(([t, n]) => (
                  <span key={t}>
                    <strong>{n}</strong>
                    <small>{t}</small>
                  </span>
                ))}
                <span>
                  <strong>{ready ? adoption!.rate : '—'}</strong>
                  <small>采纳率</small>
                  {ready && (
                    <small>
                      {adoption!.total
                        ? `已采纳 ${adoption!.adopted}/${adoption!.total}`
                        : '暂无生成用例'}
                    </small>
                  )}
                </span>
              </div>
            </section>
          )}
          {!chat && project && record && (
            <AcceptancePanel
              projectId={project.id}
              module="generate"
              refreshKey={record.serverRevision}
              recordId={Number(record.id)}
              onSessionEnd={onSessionEnd}
            />
          )}
          {!chat && (
            <div className="cg-workspace-toolbar">
              <div className="row">
                <button
                  type="button"
                  aria-expanded={historyOpen}
                  aria-controls="generation-records"
                  onClick={() => setHistoryOpen((v) => !v)}
                >
                  <Icon name="list" />
                  生成记录 · {recordChoices.length}
                </button>
              </div>
              <button
                ref={scopeToggle}
                type="button"
                aria-expanded={scopeKey !== null}
                aria-controls="generation-scope-panel"
                onClick={(e) => {
                  scopeTrigger.current = e.currentTarget;
                  setScopeKey((v) => (v === null ? '' : null));
                }}
              >
                <Icon name="file" />
                固定依据与范围 · {record?.materials.length || 0}
              </button>
            </div>
          )}
          <div
            className={`generation-layout ${chat ? 'code-chat-layout' : `generation-workbench${historyOpen ? ' has-history' : ''}`}`}
          >
            {nav}
            {nativeChat && project && record && (
              <CachedCliWorkspace
                key={`${user.id}:${project.id}:${record.id}`}
                open={chat && !detailLoading}
                projectId={project.id}
                runId={record.id}
                label={chatFunction}
                reference={reference}
                onSessionEnd={onSessionEnd}
                onClose={() => setChat(false)}
                onReviewResult={(id) => {
                  setNativeRoundId(id);
                  setTab('suggestions');
                  setChat(false);
                }}
                onSaveResult={async (id, requestId) => {
                  const next = await persist(`/${record.id}/terminal/results/${id}/save`, {
                    request_id: requestId,
                    confirmed: true,
                  });
                  if (next) {
                    setNativeRoundId(id);
                    setNotice('本轮候选已保存。');
                  }
                  return !!next;
                }}
              />
            )}
            {detailLoading ? (
              <section className="panel empty" aria-busy="true">
                <p role="status">正在读取所选生成记录的完整内容…</p>
              </section>
            ) : chat ? (
              nativeChat ? null : record && project ? (
                <GenerationChat
                  key={`${record.id}:${chatFunction}`}
                  projectId={project.id}
                  runId={record.id}
                  functionKey={
                    chatFunction === '整体'
                      ? ''
                      : record.suggestions.find((s) => s.function === chatFunction)?.functionRef ||
                        ''
                  }
                  label={chatFunction}
                  reference={reference}
                  onSessionEnd={onSessionEnd}
                  onDraft={setChatDraftTurn}
                />
              ) : (
                <section className="panel empty">选择生成记录后进入对话。</section>
              )
            ) : (
              <section className="panel generation-results">
                {!!record?.nativeRounds?.length && (
                  <div className="panel-pad">
                    <FormSelect
                      label="候选轮次"
                      value={nativeRound}
                      options={[
                        { value: '', label: '当前对话的全部轮次' },
                        ...(record.suggestions.some((s) => !s.nativeResultId)
                          ? [{ value: '__initial__', label: '首次生成候选' }]
                          : []),
                        ...record.nativeRounds.map((r) => ({
                          value: r.id,
                          label: `${new Date(r.timestamp).toLocaleString()} · ${r.caseCount}条候选`,
                        })),
                      ]}
                      onChange={setNativeRoundId}
                    />
                  </div>
                )}
                <div className="tabs change-result-tabs" role="tablist" aria-label="生成结果">
                  {(Object.entries(generationTabs) as [GenerationTab, string][]).map(
                    ([key, name], i, list) => (
                      <button
                        key={key}
                        id={`generation-tab-${key}`}
                        role="tab"
                        aria-controls="generation-result-panel"
                        aria-selected={tab === key}
                        tabIndex={tab === key ? 0 : -1}
                        onClick={() => {
                          setTab(key);
                          setPage(1);
                        }}
                        onKeyDown={(e) => {
                          if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
                          e.preventDefault();
                          const n =
                            e.key === 'Home'
                              ? 0
                              : e.key === 'End'
                                ? 2
                                : (i + (e.key === 'ArrowRight' ? 1 : 2)) % 3;
                          setTab(list[n][0]);
                          document.getElementById(`generation-tab-${list[n][0]}`)?.focus();
                        }}
                      >
                        {name}
                      </button>
                    ),
                  )}
                </div>
                {!ready ? (
                  <div
                    className="generation-scroll empty"
                    id="generation-result-panel"
                    role="tabpanel"
                    aria-labelledby={`generation-tab-${tab}`}
                  >
                    <h3>{record ? '范围已保存 · 尚无生成结果' : '暂无用例生成记录'}</h3>
                    <p>
                      {record?.cancelled
                        ? '生成已取消；已完成批次保留，未完成批次可人工重试。'
                        : '请选择资料和用例范围，或导入已有结果。'}
                    </p>
                    {record?.status === 'PREPARED' && (
                      <section className="generation-batch-plan">
                        <h3>生成前输入提示</h3>
                        <p>{record.planNote}</p>
                        <p className="hint">
                          {record.aiPreview
                            ? `本人配置：${callModeName(record.aiPreview.call_mode)} / ${record.aiPreview.name} / ${record.aiPreview.model} / v${record.aiPreview.version}`
                            : '尚未配置本人AI，开始前会拦截。'}
                        </p>
                        {record.batches.map((b) => (
                          <p className="hint" key={b.key}>
                            {b.key} · 约{b.inputBytes}字节固定输入
                          </p>
                        ))}
                        <button
                          className="primary"
                          disabled={loading || record.ownerId !== user.id}
                          onClick={() =>
                            void persist(`/${record.id}/start`, {
                              revision: record.serverRevision,
                              ai_version: record.aiPreview?.version || null,
                              ai_call_mode: record.aiPreview?.call_mode,
                              ai_preference_version: record.aiPreview?.preference_version,
                              confirmed: true,
                            })
                          }
                        >
                          {record.batches.length === 1
                            ? '继续并开始本人AI生成'
                            : '开始历史固定批次生成'}
                        </button>
                        <button disabled={loading} onClick={() => void newRecord()}>
                          缩小范围并重新准备
                        </button>
                      </section>
                    )}
                    {record?.canCancel && (
                      <button
                        className="danger small"
                        disabled={record.ownerId !== user.id}
                        onClick={() => void persist(`/${record.id}/cancel`)}
                      >
                        取消生成（仅发起人）
                      </button>
                    )}
                    {record?.cancelled && (
                      <button className="small" onClick={() => void newRecord()}>
                        重新选择范围
                      </button>
                    )}
                  </div>
                ) : tab === 'suggestions' ? (
                  <>
                    <div className="code-filters">
                      <FormSelect
                        label="建议类型"
                        value={kind}
                        options={[
                          { value: '', label: '全部建议' },
                          ...Object.entries(generationKinds).map(([value, label]) => ({
                            value,
                            label,
                          })),
                        ]}
                        onChange={(v) => {
                          setKind(v);
                          setPage(1);
                        }}
                      />
                      <FormSelect
                        label="审阅状态"
                        value={handling}
                        options={[
                          { value: '', label: '全部状态' },
                          ...['待审阅', '已忽略', '需人工确认', '已应用', '已复用'].map((v) => ({
                            value: v,
                            label: v,
                          })),
                        ]}
                        onChange={(v) => {
                          setHandling(v);
                          setPage(1);
                        }}
                      />
                      <FormSelect
                        label="功能"
                        value={feature}
                        options={[
                          { value: '', label: '全部功能' },
                          ...[...new Set(record!.suggestions.map((s) => s.function))].map((v) => ({
                            value: v,
                            label: v,
                          })),
                        ]}
                        onChange={(v) => {
                          setFeature(v);
                          setPage(1);
                        }}
                      />
                      <label className="form-field">
                        搜索用例
                        <input
                          type="search"
                          value={textQuery}
                          placeholder="标题、步骤、预期或编号"
                          onChange={(e) => {
                            setTextQuery(e.target.value);
                            setPage(1);
                          }}
                        />
                      </label>
                    </div>
                    <div
                      id="generation-result-panel"
                      role="tabpanel"
                      aria-labelledby={`generation-tab-${tab}`}
                      className="generation-scroll"
                      tabIndex={0}
                    >
                      {record!.outcome === 'PARTIAL' && (
                        <p className="generation-summary">
                          部分范围完成，未处理批次或问题仍需核对。
                        </p>
                      )}
                      {failed.length > 0 && (
                        <p className="generation-summary generation-failure">
                          {failed.length}项需人工核对，正常候选可继续审阅。
                          <button className="link" onClick={() => setFailuresOpen(true)}>
                            查看清单
                          </button>
                        </p>
                      )}
                      <GenerationTable
                        onSelectRows={(rows) =>
                          setChosen((keys) => generationSelection(record!, rows, keys))
                        }
                        onBatchReview={() => void applicationPreview()}
                        key={record!.id}
                        record={record!}
                        rows={visible}
                        filtered={filtered}
                        chosen={chosen}
                        busy={loading}
                        issues={issues}
                        duplicates={checked.filter((i) => i.matches.length > 0).map((i) => i.key)}
                        onChoose={(key, selected) =>
                          setChosen((keys) =>
                            selected ? [...new Set([...keys, key])] : keys.filter((k) => k !== key),
                          )
                        }
                        onDetail={(key) => void openDetail(key)}
                        onReview={(key) => void applicationPreview([key], record, false, true)}
                        onEvidence={(key, trigger) => {
                          scopeTrigger.current = trigger;
                          setScopeKey(key);
                        }}
                        onAsk={ask}
                        onApplied={(key) => {
                          const application = [...(record?.applications || [])]
                            .reverse()
                            .find((a) =>
                              a.items.some((i) => i.key === key && i.status === 'COMPLETED'),
                            );
                          setReviewApplicationId(application?.id || null);
                        }}
                        onResolve={resolveIssue}
                      />
                    </div>
                    <nav className="code-analysis-pagination between" aria-label="生成建议分页">
                      <span className="hint">
                        {filtered.length}条 · 每页{GENERATION_PAGE_SIZE}条 · 第{currentPage}/{pages}
                        页
                      </span>
                      <div className="row">
                        <button
                          className="small"
                          disabled={currentPage === 1}
                          onClick={() => setPage(currentPage - 1)}
                        >
                          上一页
                        </button>
                        <button
                          className="small"
                          disabled={currentPage === pages}
                          onClick={() => setPage(currentPage + 1)}
                        >
                          下一页
                        </button>
                        <PageJump page={currentPage} onChange={setPage} pages={pages} />
                      </div>
                    </nav>
                    <div className="generation-apply-bar between">
                      <span className="hint">已选{chosen.length}条（跨页/筛选）</span>
                      <div className="row">
                        <button className="ghost small" onClick={() => setChosen([])}>
                          清空
                        </button>
                        <button
                          className="primary small"
                          disabled={!chosen.length || loading}
                          onClick={() => void applicationPreview()}
                        >
                          {loading ? '读取用例版本…' : '批量审核入库'}
                        </button>
                      </div>
                    </div>
                  </>
                ) : tab === 'questions' ? (
                  <div
                    className="generation-scroll"
                    id="generation-result-panel"
                    role="tabpanel"
                    aria-labelledby={`generation-tab-${tab}`}
                    tabIndex={0}
                  >
                    {!scopedQuestions &&
                      roundRecord!.suggestions
                        .filter((s) => s.blocked && !currentHandling(record!, s)?.resolved)
                        .map(card)}
                    {!scopedQuestions && <GenerationGaps record={roundRecord!} />}
                    <GenerationCandidateIssues
                      issues={roundRecord!.candidateIssues || []}
                      onEdit={(issue) => {
                        setError('');
                        setCandidateIssue(issue);
                      }}
                    />
                    {!!questionEntries.length && <h3 className="panel-pad">业务待澄清</h3>}
                    {questionEntries.map((q) => {
                      const decision = record!.decisions
                        .filter((d) => d.questionKey === q.key)
                        .at(-1);
                      return (
                        <article className="code-finding" key={q.key}>
                          <span className="badge orange">{decision ? '已澄清' : '待澄清'}</span>
                          <h3>{q.title}</h3>
                          <p>{q.text}</p>
                          <p className="hint">{q.evidence}</p>
                          {decision && (
                            <div className="evidence">
                              {decision.conclusion}
                              <p className="hint">
                                {decision.actor} · {new Date(decision.time).toLocaleString()}
                                <br />
                                {decision.basis}
                              </p>
                            </div>
                          )}
                          <div className="row">
                            <button className="small" onClick={() => setClarify(q.key)}>
                              确认业务结论
                            </button>
                            {decision && (
                              <button
                                className="primary small"
                                onClick={() => supplement(decision)}
                              >
                                补生成受影响场景
                              </button>
                            )}
                            <button className="ghost small" onClick={() => ask(q.key, q.function)}>
                              引用提问
                            </button>
                          </div>
                        </article>
                      );
                    })}
                    {!questionEntries.length &&
                      !roundRecord!.suggestions.some((s) => s.blocked) &&
                      !generationGaps(roundRecord!).length &&
                      !roundRecord!.candidateIssues?.length && (
                        <div className="empty">暂无冲突与待澄清项。</div>
                      )}
                    <div className="panel-pad">
                      <button className="small" onClick={() => setFailuresOpen(true)}>
                        需人工确认清单（{failed.length}项）
                      </button>
                    </div>
                  </div>
                ) : (
                  <div
                    className="generation-scroll panel-pad"
                    id="generation-result-panel"
                    role="tabpanel"
                    aria-labelledby={`generation-tab-${tab}`}
                    tabIndex={0}
                  >
                    <h2>完整生成报告</h2>
                    <p className="hint">{state(record!)}</p>
                    <GenerationGaps record={roundRecord!} includeBusiness />
                    <p>{record!.scope}</p>
                    <div className="code-report-summary">
                      {Object.entries(generationKinds).map(([k, t]) => (
                        <span key={k}>
                          <strong>{record!.suggestions.filter((s) => s.kind === k).length}</strong>
                          <small>{t}建议</small>
                        </span>
                      ))}
                    </div>
                    <section className="generation-batch-plan mt">
                      <h3>{record?.nativeRounds?.length ? '候选轮次与生成进度' : '生成进度'}</h3>
                      <p className="hint">
                        {record!.batches.length
                          ? record!.nativeRounds?.length
                            ? '已保存各轮候选。'
                            : '以下为后台保存的真实批次状态；失败仅人工重试。'
                          : '尚未形成批次。'}
                      </p>
                      {record!.batches.map((b) => (
                        <div className="evidence" key={b.key}>
                          <strong>
                            {b.nativeResultId
                              ? `候选轮次 ${new Date(record!.nativeRounds?.find((r) => r.id === b.nativeResultId)?.timestamp || '').toLocaleString()}`
                              : b.key}{' '}
                            · {b.function}
                          </strong>
                          <p>
                            {b.status} · {b.nativeResultId ? '保存' : '尝试'}
                            {b.attempts}次
                          </p>
                          <p className="hint">{generationFailure(b.reason)}</p>
                          <div className="row">
                            <button
                              className="small"
                              disabled={
                                loading ||
                                !!b.nativeResultId ||
                                !['FAILED', 'CANCELLED'].includes(b.status)
                              }
                              onClick={() =>
                                void persist(`/${record!.id}/batches/${b.id}/retry`, {
                                  request_id: crypto.randomUUID(),
                                })
                              }
                            >
                              重试本批
                            </button>
                            {b.candidateAvailable && (
                              <>
                                <a
                                  className="button-link small"
                                  href={`${generationBase(project!.id)}/${record!.id}/batches/${b.id}/candidate`}
                                >
                                  下载原始候选
                                </a>
                                <button
                                  className="small"
                                  disabled={loading || b.status !== 'FAILED'}
                                  onClick={() =>
                                    void persist(`/${record!.id}/batches/${b.id}/revalidate`)
                                  }
                                >
                                  重新校验（不调用AI）
                                </button>
                              </>
                            )}
                          </div>
                        </div>
                      ))}
                    </section>
                    {roundRecord!.rawReports?.map((raw, n) => (
                      <GenerationReportDetails report={raw} index={n} key={n} />
                    ))}
                    <h3 className="mt">应用及失败记录</h3>
                    {record!.applications?.map((a) => (
                      <section className="evidence" key={a.id}>
                        <strong>
                          应用批次{a.id} · {a.status}
                        </strong>
                        <p>
                          成功{a.items.filter((i) => i.status === 'COMPLETED').length} / 失败
                          {a.items.filter((i) => i.status === 'FAILED').length} / 待处理
                          {a.items.filter((i) => i.status === 'PENDING').length}
                        </p>
                        {a.error && <p className="form-error">{generationFailure(a.error)}</p>}
                      </section>
                    ))}
                    <button className="small" onClick={() => setFailuresOpen(true)}>
                      查看需人工核对清单
                    </button>
                    <div className="row mt">
                      <button
                        className="small"
                        onClick={() => {
                          setExportIds(record ? [record.id] : []);
                          setExportOpen(true);
                        }}
                      >
                        导出完整记录/组合报告
                      </button>
                      <button
                        className="small"
                        disabled={!record!.inputText}
                        onClick={() =>
                          downloadGeneration(`${record!.id}_input.json`, record!.inputText!, true)
                        }
                      >
                        input.json
                      </button>
                      <button
                        className="small"
                        disabled={!record!.reportText}
                        onClick={() =>
                          downloadGeneration(`${record!.id}_report.json`, record!.reportText!, true)
                        }
                      >
                        report.json
                      </button>
                      <button
                        className="small"
                        onClick={() =>
                          downloadGeneration(`${record!.id}_候选用例.xlsx`, generationXlsx(record!))
                        }
                      >
                        候选14列Excel
                      </button>
                    </div>
                    <p className="hint">导出全部建议，不受分页限制。</p>
                    <h3>限制与待补充</h3>
                    {record!.limitations.map((l, i) => (
                      <p className="hint" key={i}>
                        {l}
                      </p>
                    ))}
                  </div>
                )}
              </section>
            )}
            {chat && <GenerationScope record={record} />}
          </div>
          {!chat && scopeKey !== null && (
            <aside
              id="generation-scope-panel"
              className="panel cg-scope-drawer"
              aria-label="固定依据与范围"
            >
              <div className="cg-drawer-head">
                <h2>{evidenceItem ? '本条固定依据' : '固定依据与范围'}</h2>
                <button
                  type="button"
                  id="generation-scope-close"
                  className="ghost small"
                  aria-label="关闭依据侧栏"
                  onClick={() => setScopeKey(null)}
                >
                  ×
                </button>
              </div>
              {record && evidenceItem ? (
                <>
                  <p className="cg-drawer-subtitle">
                    {evidenceItem.key} ·{' '}
                    {(currentHandling(record, evidenceItem)?.draft || evidenceItem.design).title}
                  </p>
                  <GenerationEvidence record={record} suggestion={evidenceItem} />
                  <button className="small" onClick={() => setScopeKey('')}>
                    查看记录完整范围
                  </button>
                </>
              ) : (
                <GenerationScope record={record} />
              )}
            </aside>
          )}
        </>
      )}
      {project && newOpen && options && snapshot && (
        <CaseGenerationNew
          key={`${project.id}:${snapshot.revision}`}
          projectId={project.id}
          user={user}
          options={options}
          prototypes={prototypes}
          snapshot={snapshot}
          records={recordChoices}
          busy={loading}
          serverError={error}
          onCreate={(draft) => {
            return persist('/prepare', {
              request_id: draft.id,
              title: draft.title,
              mode: draft.mode,
              scope: draft.scope,
              focus: draft.focus,
              materials: draft.materials.map((m) => ({
                document_id: m.documentId,
                version: m.version,
                before: m.before,
                update: m.update,
                paths: m.paths,
                before_paths: m.beforePaths || [],
                connection_id: m.connectionId || null,
              })),
              case_ids: draft.cases.map((c) => c.id),
              case_versions: Object.fromEntries(draft.cases.map((c) => [String(c.id), c.version])),
              case_scope: draft.caseScope,
              case_library_revision: draft.libraryRevision,
              full_scope: draft.scope === '完整所选资料',
              risk_report_ids: draft.riskReportIds || [],
              baseline_run_id: draft.baselineId ? Number(draft.baselineId) : null,
            }).then((next) => !!next);
          }}
          onClose={() => setNewOpen(false)}
          onSessionEnd={onSessionEnd}
        />
      )}
      {project && importOpen && (
        <GenerationImport
          projectId={project.id}
          onClose={() => setImportOpen(false)}
          onImported={(next) => {
            onChange([next, ...rowsRef.current.filter((r) => r.id !== next.id)]);
            choose(next.id);
            setImportOpen(false);
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
      {record && item && (
        <GenerationDetail
          key={`${record.id}:${item.key}`}
          refreshKey={detailRefresh}
          confirmationOpen={!!previewReturnKey}
          record={record}
          suggestion={item}
          actor={user.display_name}
          currentCase={snapshot?.items.find((c) => c.id === item.caseId)}
          categories={snapshot?.categories || []}
          busy={loading || !!previewReturnKey}
          applicationStatus={detailApplication?.status}
          serverError={error}
          onClose={() => setDetail('')}
          onAsk={() => ask(item.key, item.function)}
          position={{ index: Math.max(0, detailIndex), total: detailKeys.length || 1 }}
          onNext={nextDetailKey ? nextDetail : undefined}
          onPrevious={previousDetailKey ? previousDetail : undefined}
          onSave={(h, expected, intent) => {
            if ((currentHandling(record, item)?.revision || 0) !== expected) {
              setError('草稿已变化，请重新打开。');
              return;
            }
            void persist(`/${record.id}/handling`, {
              revision: record.serverRevision,
              key: item.key,
              draft: h.draft,
              note: h.note,
              ignored: h.status === '已忽略',
              evidence_checked: h.evidenceChecked,
              resolved: h.resolved,
              target_version: h.reviewedTarget?.version || null,
              category_id: h.categoryId ?? null,
              edited_fields: h.editedFields || [],
            }).then(async (next) => {
              if (next) {
                setChosen((keys) => keys.filter((k) => k !== item.key));
                if (intent === 'previous') {
                  previousDetail();
                  setNotice('人工草稿已保存，已切换上一条。');
                } else if (intent === 'next') {
                  nextDetail();
                  setNotice('人工草稿已保存，已切换下一条。');
                } else if (intent === 'review') {
                  setDetailRefresh((value) => value + 1);
                  await applicationPreview([item.key], next);
                } else {
                  setDetail('');
                  setNotice('人工草稿已保存；审核确认入库后完成设计审核。');
                }
              }
            });
          }}
        />
      )}
      {record &&
        chatDraftTurn &&
        (() => {
          const report =
            record.rawReports?.find(
              (r) =>
                Array.isArray(r.suggestions) &&
                r.suggestions.some(
                  (v: unknown) =>
                    v &&
                    typeof v === 'object' &&
                    'design' in v &&
                    v.design &&
                    typeof v.design === 'object' &&
                    'module' in v.design &&
                    v.design.module === chatFunction,
                ),
            ) || record.rawReports?.[0];
          const raw = report && Array.isArray(report.evidence) ? report.evidence : [];
          const basis = raw.find(
            (v: unknown) =>
              v &&
              typeof v === 'object' &&
              'kind' in v &&
              'side' in v &&
              (v.kind === 'DECISION' ||
                (v.kind === 'MATERIAL' &&
                  ['CURRENT', 'SUPPLEMENT', 'CONTEXT'].includes(String(v.side)))),
          );
          if (
            !basis ||
            typeof basis !== 'object' ||
            !('key' in basis) ||
            typeof basis.key !== 'string' ||
            !('target_ref' in basis) ||
            typeof basis.target_ref !== 'string' ||
            !('segment_id' in basis) ||
            typeof basis.segment_id !== 'string' ||
            !('quote' in basis) ||
            typeof basis.quote !== 'string' ||
            !('side' in basis) ||
            typeof basis.side !== 'string'
          )
            return (
              <CaseDialog title="添加草案" busy={false} onClose={() => setChatDraftTurn(null)}>
                <p className="notice">本记录缺少可绑定的当前业务证据，先补齐依据后再创建草案。</p>
              </CaseDialog>
            );
          const draft = {
            key: 'reply-draft',
            kind: 'NEW' as const,
            function: chatFunction,
            design: { ...blankDesign(), module: chatFunction === '整体' ? '' : chatFunction },
            caseId: null,
            baseVersion: null,
            reason: `从已完成对话#${chatDraftTurn}人工填写，保存草稿不审核或入库。`,
            blocked: true,
            evidence: [
              {
                source: basis.target_ref,
                segment: basis.segment_id,
                side: basis.side,
                quote: basis.quote,
              },
            ],
          };
          return (
            <GenerationDetail
              key={`reply-${chatDraftTurn}`}
              record={record}
              suggestion={draft}
              actor={user.display_name}
              onClose={() => setChatDraftTurn(null)}
              onAsk={() => setChatDraftTurn(null)}
              onSave={(h) => {
                void persist(`/${record.id}/chat/${chatDraftTurn}/draft`, {
                  request_id: crypto.randomUUID(),
                  design: h.draft,
                  evidence_refs: [basis.key],
                  note: h.note,
                  confirmed: true,
                }).then((next) => {
                  if (next) setChatDraftTurn(null);
                });
              }}
            />
          );
        })()}
      {record && candidateIssue && (
        <CandidateIssueDialog
          key={candidateIssue.key}
          issue={candidateIssue}
          busy={loading}
          error={error}
          onClose={() => setCandidateIssue(null)}
          onSave={async (payload) => {
            const next = await persist(
              `/${record.id}/batches/${candidateIssue.batchId}/candidate-issues/${encodeURIComponent(candidateIssue.issueId)}/resolve`,
              { ...payload, revision: record.serverRevision },
            );
            if (next) setCandidateIssue(null);
            return !!next;
          }}
        />
      )}
      {record && clarify && (
        <GenerationClarification
          key={`${record.id}:${clarify}`}
          record={record}
          questionKey={clarify}
          busy={loading}
          serverError={error}
          actor={user.display_name}
          onClose={() => setClarify('')}
          onSave={(d, expected) => {
            if (
              (record.decisions.filter((x) => x.questionKey === d.questionKey).at(-1)?.version ||
                0) !== expected
            ) {
              setError('结论已变化，请刷新。');
              return;
            }
            void persist(`/${record.id}/decisions`, {
              revision: record.serverRevision,
              question_key: d.questionKey,
              conclusion: d.conclusion,
              basis: d.basis,
              affected: d.affected,
              confirmed: true,
            }).then((next) => {
              if (next) {
                setClarify('');
                setNotice('已保存人工确认结论及固定来源版本；原报告保留。');
              }
            });
          }}
        />
      )}
      {record &&
        preview &&
        (preview.single && !reviewChoices[preview.items[0]?.key] ? (
          <GenerationSingleReview
            items={preview.items}
            busy={loading}
            error={error}
            onClose={closePreview}
            onSubmit={submitReview}
          />
        ) : (
          <GenerationBatchReview
            single={preview.single}
            items={preview.items}
            choices={reviewChoices}
            busy={loading}
            error={error}
            onClose={closePreview}
            onSubmit={submitReview}
          />
        ))}
      {duplicateItem && resolveKey && (
        <GenerationDuplicateResolution
          key={`${record?.id}:${duplicateItem.key}:${duplicateItem.revision}`}
          item={duplicateItem}
          choice={reviewChoices[duplicateItem.key]}
          busy={loading}
          onClose={() => setResolveKey('')}
          onSave={(choice) => {
            setReviewChoices((old) => ({ ...old, [choice.key]: choice }));
            setResolveKey('');
          }}
        />
      )}
      {record?.applications?.find((a) => a.id === reviewApplicationId) && (
        <GenerationApplicationResult
          application={record.applications.find((a) => a.id === reviewApplicationId)!}
          categories={snapshot?.categories || []}
          onClose={() => setReviewApplicationId(null)}
          onFailures={() => {
            setReviewApplicationId(null);
            setFailuresOpen(true);
          }}
        />
      )}
      {record && failuresOpen && (
        <CaseDialog
          title="需人工确认清单"
          busy={false}
          onClose={() => setFailuresOpen(false)}
          wide
          className="code-analysis-dialog change-analysis-dialog generation-dialog"
          footer={
            <footer className="change-dialog-footer">
              <button onClick={() => setFailuresOpen(false)}>关闭</button>
              <button
                disabled={!failed.length}
                onClick={() =>
                  downloadGeneration(
                    `${record.id}_需人工核对.json`,
                    JSON.stringify(
                      { record_id: record.id, note: '后台应用失败及人工处理清单', items: failed },
                      null,
                      2,
                    ),
                    true,
                  )
                }
              >
                导出清单
              </button>
            </footer>
          }
        >
          <p className="notice">修订后可重新审核失败项，成功项保留。</p>
          {failed.map((f, i) => (
            <section className="evidence" key={`${f.key}:${i}`}>
              <strong>{f.key}</strong>
              <p className="generation-failure">{f.reason}</p>
              {f.categoryMode && (
                <p className="hint">
                  本次分类：
                  {f.categoryMode === 'CLEAR'
                    ? '未分类'
                    : f.categoryMode === 'SET'
                      ? snapshot?.categories.find((c) => c.id === f.categoryId)?.name ||
                        `分类ID ${f.categoryId}（需核对）`
                      : '保持原分类'}
                </p>
              )}
              <p className="hint">
                目标 {f.caseId || '新增'} / v{f.version || '—'} ·{' '}
                {new Date(f.time).toLocaleString()}
              </p>
              <button
                className="small"
                onClick={() => {
                  setFailuresOpen(false);
                  void openDetail(f.key);
                }}
              >
                人工核对此条
              </button>
            </section>
          ))}
          {!failed.length && <div className="empty">没有需人工核对项。</div>}
        </CaseDialog>
      )}
      {exportOpen && (
        <CaseDialog
          title="导出完整记录与组合报告"
          busy={loading}
          onClose={() => setExportOpen(false)}
          className="code-analysis-dialog change-analysis-dialog generation-dialog"
          footer={
            <footer className="change-dialog-footer">
              <button disabled={loading} onClick={() => setExportOpen(false)}>
                取消
              </button>
              <button
                className="primary"
                disabled={loading || !exportIds.length}
                onClick={() => void exportRecords()}
              >
                {loading ? '读取完整记录…' : '导出全部所选记录'}
              </button>
            </footer>
          }
        >
          <p className="hint">范围和候选均完整导出，不受当前筛选/分页限制。</p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {recordChoices.map((r) => (
            <label className="check-label mt" key={r.id}>
              <input
                type="checkbox"
                disabled={loading}
                checked={exportIds.includes(r.id)}
                onChange={(e) =>
                  setExportIds((ids) =>
                    e.target.checked ? [...ids, r.id] : ids.filter((id) => id !== r.id),
                  )
                }
              />
              {r.title}
            </label>
          ))}
        </CaseDialog>
      )}
    </div>
  );
}
