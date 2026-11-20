import { AnalysisCandidateReview } from './AnalysisCandidateReview';
import { useCachedView } from './pageViewCache';
import type { PageViewCache } from './pageViewCache';
import { AIConfigurationSummary } from './AIConfigurationSummary';
import { AnalysisRecordDelete } from './AnalysisRecordDelete';
import { PageJump } from './PageJump';
import { AcceptancePanel } from './AnalysisAcceptance';
import { useEffect, useRef, useState } from 'react';
import type { Project } from './Projects';
import type { User } from './Auth';
import type { OverviewTarget } from './OverviewEntry';
import { apiDownload } from './api/http';
import { NewCodeAnalysis } from './CodeAnalysisNew';
import { ImportCodeAnalysis } from './CodeAnalysisImport';
import { CodeFindingDetail } from './CodeAnalysisDetail';
import { CodeAnalysisChat } from './CodeAnalysisChat';
import { AnalysisCliHistory, useHistoryButton } from './AnalysisCliHistory';
import {
  codeError,
  codeErrors,
  codeEvidenceStates,
  codeHandlingStates,
  codeKinds,
  codeLevels,
  codeList,
  codeOutcomes,
  codeRequest,
  codeStates,
  codeTargets,
  parseCodeDetail,
  parseCodeOptions,
} from './codeAnalysisApi';
import type { CodeDetail, CodeOptions, CodeRecord, CodeTarget } from './codeAnalysisApi';
import './code-analysis.css';
import './requirement-ui.css';

type Props = {
  pageCache?: PageViewCache;
  onRecordDeleted?: () => void;
  project: Project | null;
  user: User;
  onSessionEnd: () => void;
  overviewTarget?: OverviewTarget | null;
};
export function CodeAnalysis(props: Props) {
  const [deletionVersion, setDeletionVersion] = useState(0);
  return (
    <CodeWorkspace
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

export function CodeScope({ record }: { record: CodeDetail | null }) {
  return (
    <aside className="panel code-analysis-scope">
      <div className="panel-head">
        <h2>本记录范围</h2>
        <span className="badge">只读</span>
      </div>
      <div className="panel-pad">
        {record?.input?.sources.map((source) => (
          <section className="evidence" key={source.source_id}>
            <strong>{source.name}</strong>
            <p className="hint">
              {source.source_kind === 'LOCAL' ? '本地' : 'GitHub'} ·{' '}
              {codeKinds[source.repository_kind]}
            </p>
            <p className="mono hint">{source.snapshot_ref}</p>
            <details>
              <summary>选定文件 · {source.files.length}个</summary>
              {source.files.map((file) => (
                <p className="mono hint" key={file.file_id}>
                  {file.path} · {file.read_state}
                </p>
              ))}
            </details>
          </section>
        ))}
        {!record?.input && (
          <p className="hint">
            {record?.status === 'QUEUED' || record?.status === 'RUNNING'
              ? '后台正在准备固定内容。'
              : '请选择分析记录。'}
          </p>
        )}
        {!!record?.input?.materials.length && (
          <>
            <h3 className="mt">需求与原型依据</h3>
            {record.input.materials.map((material) => (
              <div className="evidence" key={material.source_id}>
                <strong>{material.name}</strong>
                <p className="hint">
                  {material.origin} · {material.read_state}
                </p>
                <p className="hint mono">{material.snapshot_ref}</p>
              </div>
            ))}
          </>
        )}
        <p className="hint mt">
          {record?.origin === 'IMPORT'
            ? '导入快照尚未与真实仓库比对。'
            : '分析使用创建时的固定范围。'}
        </p>
      </div>
    </aside>
  );
}

function CodeWorkspace({
  project,
  user,
  onSessionEnd,
  overviewTarget,
  onRecordDeleted,
  pageCache,
}: Props) {
  const [rows, setRows] = useState<CodeRecord[]>([]),
    [options, setOptions] = useState<CodeOptions | null>(null),
    [selected, setSelected] = useCachedView<number | null>(
      pageCache,
      'selected',
      overviewTarget?.id ?? null,
    ),
    [record, setRecord] = useState<CodeDetail | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(true),
    [detailLoading, setDetailLoading] = useState(false),
    [starting, setStarting] = useState(false),
    [importing, setImporting] = useState(false),
    [chat, setChat] = useState(false),
    [findingKey, setFindingKey] = useState(''),
    [chatFinding, setChatFinding] = useState(''),
    [target, setTarget] = useCachedView<CodeTarget | 'ALL'>(pageCache, 'target', 'ALL'),
    [page, setPage] = useCachedView(pageCache, 'page', 1),
    [recordPage, setRecordPage] = useState(1),
    [hasMore, setHasMore] = useState(false),
    [busy, setBusy] = useState(false),
    [refresh, setRefresh] = useState(0),
    [notice, setNotice] = useState('');
  const controller = useRef(new AbortController()),
    loadedMore = useRef(false),
    retryIds = useRef(new Map<number, string>());
  const base = `/api/projects/${project?.id}/code-analysis`;
  const historyButton = useHistoryButton(chat);
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  useEffect(() => {
    if (!project) {
      setLoading(false);
      return;
    }
    const c = new AbortController();
    let polling = false;
    async function load() {
      if (polling) return;
      polling = true;
      try {
        const result = await codeList(base, c.signal);
        if (!c.signal.aborted) {
          setRows((old) =>
            [...new Map([...old, ...result.items].map((item) => [item.id, item])).values()].sort(
              (a, b) => b.id - a.id,
            ),
          );
          setSelected((old) => old ?? result.items[0]?.id ?? null);
          if (!loadedMore.current) setHasMore(result.has_more);
          setError('');
        }
      } catch (reason) {
        if (
          !c.signal.aborted &&
          reason instanceof Error &&
          ['not_authenticated', 'project_not_found'].includes(reason.message)
        ) {
          setRows([]);
          setRecord(null);
        }
        if (!c.signal.aborted) setError(codeError(reason, onSessionEnd));
      } finally {
        polling = false;
        if (!c.signal.aborted) setLoading(false);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 4000);
    return () => {
      clearInterval(timer);
      c.abort();
    };
  }, [base, project, onSessionEnd, refresh, setSelected]);
  useEffect(() => {
    if (!project) return;
    const c = new AbortController();
    codeRequest(`${base}/options`, parseCodeOptions, { signal: c.signal })
      .then((value) => {
        if (!c.signal.aborted) setOptions(value);
      })
      .catch((reason) => {
        if (!c.signal.aborted) setError(codeError(reason, onSessionEnd));
      });
    return () => c.abort();
  }, [base, project, onSessionEnd, refresh]);
  const selectedActive = rows.some(
    (row) => row.id === selected && (row.status === 'QUEUED' || row.status === 'RUNNING'),
  );
  useEffect(() => {
    if (!selected) return;
    const c = new AbortController();
    let fetching = false;
    setDetailLoading(true);
    async function load() {
      if (fetching) return;
      fetching = true;
      try {
        const value = await codeRequest(`${base}/${selected}`, parseCodeDetail, {
          signal: c.signal,
        });
        if (!c.signal.aborted) {
          setRecord(value);
          setRows((old) =>
            [value, ...old.filter((row) => row.id !== value.id)].sort((a, b) => b.id - a.id),
          );
        }
      } catch (reason) {
        if (
          !c.signal.aborted &&
          reason instanceof Error &&
          ['not_authenticated', 'project_not_found'].includes(reason.message)
        ) {
          setRows([]);
          setRecord(null);
        }
        if (!c.signal.aborted) setError(codeError(reason, onSessionEnd));
      } finally {
        fetching = false;
        if (!c.signal.aborted) setDetailLoading(false);
      }
    }
    void load();
    const timer = selectedActive ? setInterval(() => void load(), 2500) : undefined;
    return () => {
      if (timer) clearInterval(timer);
      c.abort();
    };
  }, [base, selected, selectedActive, onSessionEnd, refresh]);
  function choose(id: number) {
    setSelected(id);
    setRecord(null);
    setPage(1);
    setTarget('ALL');
    setFindingKey('');
    setChatFinding('');
    setError('');
  }
  function applied(value: CodeDetail) {
    setRows((old) =>
      [value, ...old.filter((row) => row.id !== value.id)].sort((a, b) => b.id - a.id),
    );
    setSelected(value.id);
    setRecord(value);
    setPage(1);
    setTarget('ALL');
    setFindingKey('');
    setStarting(false);
    setImporting(false);
    if (value.terminal_available && ['QUEUED', 'RUNNING'].includes(value.status)) {
      setChatFinding('');
      setChat(true);
    }
    setNotice(value.duplicate ? '相同输入和结果已导入，已打开原记录。' : '');
    setRefresh((v) => v + 1);
  }
  function savedHandling(value: CodeDetail) {
    setRecord(value);
    setRows((old) => old.map((row) => (row.id === value.id ? value : row)));
    setFindingKey('');
  }
  async function more() {
    if (busy) return;
    setBusy(true);
    try {
      const result = await codeList(`${base}?page=${recordPage + 1}`, controller.current.signal);
      if (!controller.current.signal.aborted) {
        setRows((old) =>
          [...new Map([...old, ...result.items].map((item) => [item.id, item])).values()].sort(
            (a, b) => b.id - a.id,
          ),
        );
        setRecordPage((v) => v + 1);
        loadedMore.current = true;
        setHasMore(result.has_more);
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function action(kind: 'cancel' | 'retry' | 'revalidate') {
    if (!record || busy) return;
    setBusy(true);
    setError('');
    if (kind === 'retry' && !retryIds.current.has(record.id))
      retryIds.current.set(record.id, crypto.randomUUID());
    try {
      const value = await codeRequest(`${base}/${record.id}/${kind}`, parseCodeDetail, {
        method: 'POST',
        signal: controller.current.signal,
        ...(kind === 'retry'
          ? { body: JSON.stringify({ request_id: retryIds.current.get(record.id) }) }
          : {}),
      });
      if (!controller.current.signal.aborted) {
        applied(value);
        if (kind === 'revalidate') setNotice('已重新校验保存的AI候选；没有再次调用AI。');
      }
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function download(format: 'markdown' | 'input' | 'report') {
    if (!record || busy) return;
    setBusy(true);
    try {
      const blob = await apiDownload(`${base}/${record.id}/export?format=${format}`, {
        signal: controller.current.signal,
      });
      if (controller.current.signal.aborted) return;
      const url = URL.createObjectURL(blob),
        link = document.createElement('a');
      link.href = url;
      link.download = format === 'markdown' ? `code-analysis-${record.id}.md` : `${format}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  async function downloadCandidate() {
    if (!record || busy || !record.candidate_available) return;
    setBusy(true);
    try {
      const blob = await apiDownload(`${base}/${record.id}/candidate`, {
        signal: controller.current.signal,
      });
      if (controller.current.signal.aborted) return;
      const url = URL.createObjectURL(blob),
        link = document.createElement('a');
      link.href = url;
      link.download = `code-analysis-${record.id}-ai-candidate.txt`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      if (!controller.current.signal.aborted) setError(codeError(reason, onSessionEnd));
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  const findings = record?.report?.findings || [],
    filtered = findings.filter(
      (f) =>
        (target === 'ALL' || f.target_refs.includes(target)) &&
        (!overviewTarget?.state ||
          record?.id !== overviewTarget.id ||
          (record.handling[f.key]?.status || 'PENDING') === overviewTarget.state),
    ),
    pages = Math.max(1, Math.ceil(filtered.length / 10)),
    currentPage = Math.min(page, pages),
    visible = filtered.slice((currentPage - 1) * 10, currentPage * 10),
    finding = findings.find((f) => f.key === findingKey);
  const records = (
    <aside className="panel code-analysis-records">
      <div className="panel-head">
        <h2>分析记录</h2>
        <span className="badge">{rows.length}</span>
      </div>
      {rows.map((row) => (
        <div className="analysis-record-row" key={row.id}>
          <button
            className={`code-record ${row.id === selected ? 'active' : ''}`}
            onClick={() => choose(row.id)}
          >
            <strong>{row.title}</strong>
            <small>
              {new Date(row.created_at).toLocaleString()} · {codeStates[row.status]} ·{' '}
              {row.origin === 'IMPORT' ? '导入' : 'AI分析'}
            </small>
          </button>
          {project && (
            <AnalysisRecordDelete
              base={base}
              id={row.id}
              projectId={project.id}
              iconOnly
              recordTitle={row.title}
              canDelete={
                user.platform_role === 'ADMIN' || project.can_manage || row.actor_id === user.id
              }
              refreshKey={row.revision}
              onDeleted={onRecordDeleted}
              onSessionEnd={onSessionEnd}
            />
          )}
        </div>
      ))}
      {!rows.length && <p className="hint panel-pad">暂无代码分析记录。</p>}
      {hasMore && (
        <button className="ghost small" disabled={busy} onClick={() => void more()}>
          更多记录
        </button>
      )}
    </aside>
  );
  return (
    <div className="code-analysis-page requirement-ui">
      <header className="page-head">
        <div>
          <h1>{chat ? '代码分析对话' : '代码分析'}</h1>
          <p>
            {chat
              ? '独立代码审查对话；按分析记录使用固定上下文。'
              : '先选择分析记录，再查看该记录的固定结果。'}
          </p>
        </div>
        <div className="head-actions">
          {chat ? (
            <button className="ghost" onClick={() => setChat(false)}>
              返回代码分析
            </button>
          ) : (
            <>
              <button
                className="primary"
                disabled={!project || !options}
                onClick={() => setStarting(true)}
              >
                新建代码分析
              </button>
              <button
                className="ghost"
                disabled={!project || !options}
                onClick={() => setImporting(true)}
              >
                导入代码分析
              </button>
              <button ref={historyButton} className="ghost" onClick={() => setChat(true)}>
                历史对话
              </button>
            </>
          )}
          <button className="ghost small" onClick={() => setRefresh((v) => v + 1)}>
            刷新
          </button>
        </div>
      </header>
      {!project && <p className="notice">请先选择项目。</p>}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading && <p role="status">正在加载代码分析记录…</p>}
      {project && record?.terminal_available && (
        <div className="code-chat-layout analysis-native-history-layout" hidden={!chat}>
          {chat && records}
          <AnalysisCliHistory
            kind="code"
            projectId={project.id}
            recordId={record.id}
            open={chat}
            cancelUrl={`${base}/${record.id}/cancel`}
            reference={chatFinding}
            onClose={() => setChat(false)}
            onInitialFinished={() => setRefresh((v) => v + 1)}
            errorMessage={(e) => codeError(e, onSessionEnd)}
          />
          {chat && <CodeScope record={record} />}
        </div>
      )}
      {chat ? (
        !record?.terminal_available && (
          <div className="code-chat-layout">
            {records}
            {record ? (
              <CodeAnalysisChat
                key={record.id}
                record={record}
                findingKey={chatFinding}
                onClearFinding={() => setChatFinding('')}
                onSessionEnd={onSessionEnd}
              />
            ) : (
              <section className="panel panel-pad">
                <p className="hint">{detailLoading ? '加载记录中…' : '请选择完成的分析记录。'}</p>
              </section>
            )}
            <CodeScope record={record} />
          </div>
        )
      ) : (
        <>
          {record?.report && (
            <div className="code-goal-summary">
              {record.report.target_results.map((goal) => (
                <section className="code-goal-row" key={goal.target}>
                  <strong>{codeTargets[goal.target]}</strong>
                  <span className="badge">{codeOutcomes[goal.status]}</span>
                  <p className="hint">{goal.scope}</p>
                  <span className="hint">关联发现 {goal.finding_refs.length} 条</span>
                </section>
              ))}
            </div>
          )}
          <section className="code-analysis-overview panel">
            <div>
              <span className="eyebrow">代码检查 · 分析记录</span>
              <h2>{record?.title || '尚未选择分析记录'}</h2>

              <p className="hint">
                {rows.length}次记录 · 当前{findings.length}条发现 · 每页10条
              </p>
            </div>
            <div className="code-analysis-stats">
              <span>
                <strong>{findings.filter((f) => f.severity === 'HIGH').length}</strong>
                <small>高风险</small>
              </span>
              <span>
                <strong>
                  {findings.filter((f) => f.evidence_state === 'INSUFFICIENT').length}
                </strong>
                <small>证据不足</small>
              </span>
              <span>
                <strong>{findings.length}</strong>
                <small>当前记录发现</small>
              </span>
            </div>
          </section>
          {project && record && (
            <AcceptancePanel
              projectId={project.id}
              module="code"
              refreshKey={record.revision}
              recordId={record.id}
              onSessionEnd={onSessionEnd}
            />
          )}
          <div className="code-analysis-workspace">
            {records}
            <section className="panel code-analysis-results">
              <div className="panel-head">
                <div>
                  <h2>代码分析发现</h2>
                  <p className="hint">
                    {record ? codeStates[record.status] : '未选择记录'} · 来源和版本见右侧
                  </p>
                </div>
                {record?.report && (
                  <div className="row code-export-actions">
                    {record.candidate_available && (
                      <AnalysisCandidateReview
                        endpoint={`/api/projects/${project?.id}/code-analysis/${record.id}/candidate-review`}
                        onSessionEnd={onSessionEnd}
                      />
                    )}
                    {record.candidate_available && (
                      <button
                        className="ghost small"
                        disabled={busy}
                        onClick={() => void downloadCandidate()}
                      >
                        AI候选原文
                      </button>
                    )}
                    <button
                      className="ghost small"
                      disabled={busy}
                      onClick={() => void download('markdown')}
                    >
                      导出发现
                    </button>
                    <button
                      className="ghost small"
                      disabled={busy}
                      onClick={() => void download('input')}
                    >
                      输入JSON
                    </button>
                    <button
                      className="ghost small"
                      disabled={busy}
                      onClick={() => void download('report')}
                    >
                      结果JSON
                    </button>
                  </div>
                )}
              </div>
              {detailLoading && (
                <p role="status" className="panel-pad">
                  正在加载固定结果…
                </p>
              )}
              <p className="panel-pad">
                <AIConfigurationSummary value={record?.ai} />
              </p>
              {record && record.status !== 'COMPLETED' && (
                <div className="evidence">
                  <strong>{codeStates[record.status]}</strong>
                  <p>
                    {record.error_code
                      ? codeErrors[record.error_code] || '任务未完成，请核对配置和输入后重试。'
                      : '任务在后台处理，离开页面仍会继续。'}
                  </p>
                  <div className="row">
                    {record.candidate_available && (
                      <AnalysisCandidateReview
                        endpoint={`/api/projects/${project?.id}/code-analysis/${record.id}/candidate-review`}
                        onSessionEnd={onSessionEnd}
                      />
                    )}
                    {record.candidate_available && (
                      <button
                        className="ghost small"
                        disabled={busy}
                        onClick={() => void downloadCandidate()}
                      >
                        AI候选原文
                      </button>
                    )}
                    {record.can_cancel && (
                      <button
                        className="ghost small"
                        disabled={busy}
                        onClick={() => void action('cancel')}
                      >
                        取消分析
                      </button>
                    )}
                    {record.can_retry && (
                      <button disabled={busy} onClick={() => void action('retry')}>
                        使用我的AI配置重试
                      </button>
                    )}
                    {record.can_revalidate && (
                      <button
                        className="ghost small"
                        disabled={busy}
                        onClick={() => void action('revalidate')}
                      >
                        重新校验候选
                      </button>
                    )}
                  </div>
                </div>
              )}
              {record?.origin === 'LEGACY' && (
                <p className="notice">历史v1记录未转换，请新建或导入v2结果。</p>
              )}
              {record?.report && (
                <p className="code-report-conclusion">{record.report.summary.conclusion}</p>
              )}
              {record && record.evidence_corrections.length > 0 && (
                <p className="hint panel-pad">
                  {record.evidence_corrections.length}
                  条证据的行号或末尾换行已按固定原文校正；原始AI候选可下载核对。
                </p>
              )}
              <div className="code-filters">
                {(['ALL', ...(record?.targets || [])] as const).map((value) => (
                  <button
                    className="small"
                    key={value}
                    aria-pressed={target === value}
                    onClick={() => {
                      setTarget(value);
                      setPage(1);
                    }}
                  >
                    {value === 'ALL' ? '全部' : codeTargets[value]}
                  </button>
                ))}
              </div>
              {visible.map((item) => (
                <article className="code-finding" key={item.key}>
                  <div className="row">
                    <span className="badge">{item.category}</span>
                    <span className="hint mono">{item.key}</span>
                  </div>
                  <div className="row code-finding-badges mt">
                    <span className={`badge ${item.severity === 'HIGH' ? 'red' : 'orange'}`}>
                      严重程度：{codeLevels[item.severity]}
                    </span>
                    <span className="badge">{codeEvidenceStates[item.evidence_state]}</span>
                    <span className="badge">
                      {codeHandlingStates[record?.handling[item.key]?.status || 'PENDING']}
                    </span>
                  </div>
                  <div className="row mt">
                    {item.target_refs.map((t) => (
                      <span className="badge blue" key={t}>
                        {codeTargets[t]}
                      </span>
                    ))}
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.actual}</p>
                  <div className="code-finding-chain">
                    {item.target_refs.includes('REQUIREMENT_DEVIATION')
                      ? '需求依据 → 当前实现 → 偏差核查'
                      : item.target_refs.includes('FRONTEND_BACKEND_MISMATCH')
                        ? '响应字段 → 客户端解析 → 差异核查'
                        : '执行条件 → 相关代码 → 错误核查'}
                  </div>
                  <div className="between mt">
                    <span className="hint">静态分析 · 未运行验证</span>
                    <button className="link" onClick={() => setFindingKey(item.key)}>
                      查看分析内容 →
                    </button>
                  </div>
                </article>
              ))}
              {!visible.length && !detailLoading && (
                <div className="empty">
                  <h3>{record?.report ? '当前目标没有代码发现' : '尚未取得分析结果'}</h3>
                </div>
              )}
              {!!filtered.length && (
                <nav className="code-analysis-pagination" aria-label="代码发现分页">
                  <span>
                    筛选后{filtered.length}条 / 当前记录{findings.length}条 · 第{currentPage}/
                    {pages}页
                  </span>
                  <div className="row">
                    <button disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>
                      上一页
                    </button>
                    <button
                      disabled={currentPage === pages}
                      onClick={() => setPage(currentPage + 1)}
                    >
                      下一页
                    </button>
                    <PageJump page={currentPage} onChange={setPage} pages={pages} />
                  </div>
                </nav>
              )}
              {!!record?.report?.limitations.length && (
                <details className="evidence">
                  <summary>范围与限制</summary>
                  {record.report.limitations.map((item) => (
                    <p className="hint" key={item.key}>
                      {item.detail}
                      <br />
                      {item.effect}
                    </p>
                  ))}
                </details>
              )}
            </section>
            <CodeScope record={record} />
          </div>
        </>
      )}
      {starting && project && options && (
        <NewCodeAnalysis
          projectId={project.id}
          user={user}
          options={options}
          onSessionEnd={onSessionEnd}
          onClose={() => setStarting(false)}
          onCreated={applied}
        />
      )}{' '}
      {importing && project && options && (
        <ImportCodeAnalysis
          projectId={project.id}
          options={options}
          onSessionEnd={onSessionEnd}
          onClose={() => setImporting(false)}
          onImported={applied}
        />
      )}{' '}
      {record && finding && (
        <CodeFindingDetail
          key={`${record.id}:${finding.key}:${record.revision}`}
          record={record}
          finding={finding}
          onClose={() => setFindingKey('')}
          onSaved={savedHandling}
          onAsk={(key) => {
            setFindingKey('');
            setChatFinding(key);
            setChat(true);
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
    </div>
  );
}
