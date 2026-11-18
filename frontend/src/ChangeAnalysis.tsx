import { AnalysisCandidateReview } from './AnalysisCandidateReview';
import { AIConfigurationSummary } from './AIConfigurationSummary';
import { AnalysisRecordDelete } from './AnalysisRecordDelete';
import { PageJump } from './PageJump';
import { AcceptancePanel } from './AnalysisAcceptance';
import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from './Icon';
import type { Project } from './Projects';
import type { User } from './Auth';
import type { OverviewTarget } from './OverviewEntry';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { ChangeAnalysisNew } from './ChangeAnalysisNew';
import { ChangeImport } from './ChangeImport';
import { ChangeAnalysisChat } from './ChangeAnalysisChat';
import { apiDownload } from './api/http';
import {
  changeDetail,
  changeError,
  changeListing,
  changeStates,
  changeTargets,
  handlingStates,
} from './changeAnalysisApi';
import { codeError, codeRequest, parseCodeOptions } from './codeAnalysisApi';
import type { CodeOptions } from './codeAnalysisApi';
import {
  changeCauses,
  changeItems,
  changeModes,
  changeTabs,
  downloadChange,
} from './changeAnalysisPage';
import type { ChangeItem, ChangeTab, PageChangeRecord } from './changeAnalysisPage';
import './code-analysis.css';
import './requirement-ui.css';
import './change-analysis.css';

type Props = {
  onRecordDeleted?: () => void;
  overviewTarget?: OverviewTarget | null;
  project: Project | null;
  user: User;
  rows?: PageChangeRecord[];
  onChange?: (rows: PageChangeRecord[]) => void;
  onSessionEnd: () => void;
};
export function ChangeAnalysis(props: Props) {
  const [deletionVersion, setDeletionVersion] = useState(0);
  return (
    <ChangeWorkspace
      key={`${props.user.id}:${props.project?.id}:${deletionVersion}`}
      {...props}
      overviewTarget={deletionVersion ? null : props.overviewTarget}
      onRecordDeleted={() => setDeletionVersion((v) => v + 1)}
    />
  );
}
function status(record: PageChangeRecord) {
  if (record.status === 'COMPLETED' && record.batches?.failed) return '部分批次失败';
  return record.status
    ? changeStates[record.status] || record.status
    : record.status !== 'COMPLETED'
      ? '范围草稿'
      : '本页预览';
}
function Evidence({ item }: { item: ChangeItem }) {
  return (
    <>
      <p className="hint mono">{item.location}</p>
      <div className="form-grid change-evidence">
        <section className="evidence">
          <strong>旧版本 · BEFORE</strong>
          <pre>{item.before || '未提供旧证据'}</pre>
        </section>
        <section className="evidence">
          <strong>新版本 · AFTER</strong>
          <pre>{item.after || '未提供新证据'}</pre>
        </section>
      </div>
    </>
  );
}
function SelectedFiles({ paths }: { paths: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>选定范围 · {paths.length}项</summary>
      {open &&
        paths.map((path) => (
          <p className="hint mono" key={path}>
            {path}
          </p>
        ))}
    </details>
  );
}
function ChangeScope({
  record,
  onCompare,
}: {
  record: PageChangeRecord | null;
  onCompare: () => void;
}) {
  return (
    <aside className="panel code-analysis-scope">
      <h2>固定比较范围</h2>
      <div className="panel-pad">
        {record ? (
          <>
            {record.pairs.map((p, i) => (
              <section className="evidence" key={i}>
                <strong>{p.name}</strong>
                <p className="hint">旧基准</p>
                <p className="mono">{p.before}</p>
                <p className="hint">新目标</p>
                <p className="mono">{p.after}</p>
                <p>{p.update}</p>
                {p.update.includes('增量') && (
                  <p className="hint">未提及的旧规则继续适用，不逐条列出或计入变化数量。</p>
                )}
                <SelectedFiles key={`${record.id}:${i}`} paths={p.scope} />
              </section>
            ))}
            <button className="link" onClick={onCompare}>
              查看新旧对照
            </button>
            <h3 className="mt">已选固定引用</h3>
            {record.context.map((x) => (
              <p className="hint" key={x}>
                {x}
              </p>
            ))}
            {!record.context.length && <p className="hint">未带入补充依据。</p>}
            <h3 className="mt">目标处理情况</h3>
            {record.targets.map((x) => (
              <div className="evidence" key={x}>
                <strong>{x}</strong>
                <p>
                  <span className="badge orange">
                    {(
                      {
                        COMPLETE: '本范围已核查',
                        PARTIAL: '部分核查',
                        BLOCKED: '依据不足／未执行',
                      } as Record<string, string>
                    )[record.targetResults?.find((t) => t.name === x)?.status || ''] ||
                      status(record)}
                  </span>
                </p>
                {record.targetResults?.find((t) => t.name === x)?.note && (
                  <p className="hint">{record.targetResults.find((t) => t.name === x)?.note}</p>
                )}
              </div>
            ))}
            <h3 className="mt">范围与证据缺口</h3>
            <p className="hint">
              {record.status !== 'COMPLETED'
                ? '任务尚未完成；以已固定输入为依据，不按零风险解读。'
                : '结果已通过契约与引用校验；静态判断仍需人工审阅。'}
            </p>
            {record.limitations?.map((note, i) => (
              <p className="hint" key={i}>
                {note}
              </p>
            ))}
            <p className="hint">缺少代码或用例不代表无影响；旧问题未再次出现不自动关闭。</p>
          </>
        ) : (
          <p className="hint">选择记录后显示新旧版本和范围。</p>
        )}
      </div>
    </aside>
  );
}
function ChangeWorkspace({
  project,
  user,
  rows: initialRows = [],
  onRecordDeleted,
  onSessionEnd,
  overviewTarget,
}: Props) {
  const [rows, setRows] = useState<PageChangeRecord[]>(initialRows),
    [listPage, setListPage] = useState(1),
    [hasMore, setHasMore] = useState(false),
    [actionBusy, setActionBusy] = useState(false);
  const listBusy = useRef<AbortController | null>(null);
  function onChange(next: PageChangeRecord[]) {
    setRows(next);
  }
  const [selected, setSelected] = useState(overviewTarget ? String(overviewTarget.id) : ''),
    [tab, setTab] = useState<ChangeTab>(
      overviewTarget?.group === 'regressions'
        ? 'regressions'
        : overviewTarget?.group === 'impacts'
          ? 'impacts'
          : 'changes',
    ),
    [page, setPage] = useState(1),
    [query, setQuery] = useState(''),
    [functionFilter, setFunctionFilter] = useState(''),
    [causeFilter, setCauseFilter] = useState(''),
    [handlingFilter, setHandlingFilter] = useState(
      overviewTarget?.state
        ? overviewTarget.state === 'PENDING' && overviewTarget.group === 'regressions'
          ? '待审阅'
          : handlingStates[overviewTarget.state]
        : '',
    ),
    [options, setOptions] = useState<CodeOptions | null>(null),
    [newOpen, setNewOpen] = useState(false),
    [importOpen, setImportOpen] = useState(false),
    [chat, setChat] = useState(false),
    [reference, setReference] = useState(''),
    [detail, setDetail] = useState<{ tab: ChangeTab; key: string } | null>(null),
    [compare, setCompare] = useState(false),
    [exporting, setExporting] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [loading, setLoading] = useState(false);
  const generation = useRef(new AbortController());
  useEffect(() => {
    const c = new AbortController();
    generation.current = c;
    return () => c.abort();
  }, []);
  const record = rows.find((x) => x.id === selected) || (selected ? null : rows[0]) || null;
  const base = `/api/projects/${project?.id || 0}/change-analysis`;
  useEffect(() => {
    if (!project || !overviewTarget) return;
    const c = new AbortController();
    setLoading(true);
    void changeDetail(`${base}/${overviewTarget.id}?page_view=true`, project.id, {
      signal: c.signal,
    })
      .then((value) => {
        if (!c.signal.aborted) setRows((old) => [value, ...old.filter((r) => r.id !== value.id)]);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(changeError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [base, project, overviewTarget, onSessionEnd]);
  useEffect(() => {
    if (!project) return;
    const c = new AbortController();
    async function refresh() {
      if (listBusy.current && !listBusy.current.signal.aborted) return;
      listBusy.current = c;
      try {
        const result = await changeListing(`${base}?page=1&page_view=true`, project!.id, c.signal);
        if (c.signal.aborted) return;
        setHasMore((old) => (listPage === 1 ? result.has_more : old));
        setRows((old) => {
          const map = new Map(old.map((r) => [r.id, r]));
          let changed = false;
          for (const summary of result.items) {
            const previous = map.get(summary.id);
            if (
              previous &&
              previous.updatedAt === summary.updatedAt &&
              previous.revision === summary.revision &&
              previous.actorId === summary.actorId &&
              previous.can_retry === summary.can_retry &&
              previous.retry_replan === summary.retry_replan
            )
              continue;
            changed = true;
            const keepInput =
              previous?.loaded &&
              !!previous.inputText &&
              previous.inputText !== '{}' &&
              ['QUEUED', 'RUNNING', 'PREPARED'].includes(previous.status || '') &&
              ['QUEUED', 'RUNNING', 'PREPARED'].includes(summary.status || '') &&
              previous.revision === summary.revision;
            map.set(summary.id, {
              ...previous,
              ...summary,
              ...(keepInput ? { pairs: previous.pairs, context: previous.context } : {}),
              loaded: !!keepInput,
            });
          }
          return changed ? [...map.values()].sort((a, b) => Number(b.id) - Number(a.id)) : old;
        });
      } catch (e) {
        if (
          !c.signal.aborted &&
          e instanceof Error &&
          ['not_authenticated', 'project_not_found'].includes(e.message)
        )
          setRows([]);
        if (!c.signal.aborted) setError(changeError(e, onSessionEnd));
      } finally {
        if (listBusy.current === c) listBusy.current = null;
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 3500);
    return () => {
      c.abort();
      clearInterval(timer);
    };
  }, [base, project, onSessionEnd, listPage]);
  useEffect(() => {
    if (!project || !record || record.loaded || !record.status) return;
    const c = new AbortController();
    void changeDetail(`${base}/${record.id}?page_view=true`, project.id, { signal: c.signal })
      .then((result) => {
        if (!c.signal.aborted) setRows((old) => old.map((r) => (r.id === result.id ? result : r)));
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(changeError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [base, project, record, onSessionEnd]);
  async function moreRecords() {
    if (!project || (listBusy.current && !listBusy.current.signal.aborted)) return;
    const c = generation.current;
    listBusy.current = c;
    try {
      const result = await changeListing(
        `${base}?page=${listPage + 1}&page_view=true`,
        project.id,
        generation.current.signal,
      );
      if (generation.current.signal.aborted) return;
      setRows((old) =>
        [...new Map([...old, ...result.items].map((r) => [r.id, r])).values()].sort(
          (a, b) => Number(b.id) - Number(a.id),
        ),
      );
      setListPage((v) => v + 1);
      setHasMore(result.has_more);
    } catch (e) {
      if (!generation.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      if (listBusy.current === c) listBusy.current = null;
    }
  }
  async function operate(action: string, body?: unknown) {
    if (!project || !record || actionBusy) return;
    setActionBusy(true);
    setError('');
    try {
      const next = await changeDetail(`${base}/${record.id}/${action}`, project.id, {
        method: 'POST',
        signal: generation.current.signal,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (generation.current.signal.aborted) return;
      setRows((old) => [next, ...old.filter((r) => r.id !== next.id)]);
      setSelected(next.id);
      setDetail(null);
      setNotice(
        action === 'retry'
          ? '已创建重试任务，原失败记录保留。'
          : action === 'handling'
            ? '人工处理已保存；未修改原报告、用例或旧问题。'
            : '任务状态已更新。',
      );
    } catch (e) {
      if (!generation.current.signal.aborted) setError(changeError(e, onSessionEnd));
    } finally {
      if (!generation.current.signal.aborted) setActionBusy(false);
    }
  }
  async function exportRecord(format: string) {
    if (!record || !project) return;
    try {
      const body = await apiDownload(
        `${base}/${record.id}/${format === 'candidate' ? 'candidate' : `export?format=${format}`}`,
        { signal: generation.current.signal },
      );
      if (!generation.current.signal.aborted)
        downloadChange(
          format === 'input'
            ? 'input.json'
            : format === 'report'
              ? 'report.json'
              : `${record.title}.${format === 'candidate' ? 'txt' : 'md'}`,
          await body.text(),
          format === 'input' || format === 'report',
        );
    } catch (e) {
      if (!generation.current.signal.aborted) setError(changeError(e, onSessionEnd));
    }
  }

  function resetFilters() {
    setPage(1);
    setFunctionFilter('');
    setCauseFilter('');
    setHandlingFilter('');
  }
  function choose(id: string) {
    setSelected(id);
    setDetail(null);
    setCompare(false);
    setReference('');
    resetFilters();
  }
  async function openNew() {
    if (!project || loading) return;
    setLoading(true);
    setError('');
    try {
      const value = await codeRequest(
        `/api/projects/${project.id}/code-analysis/options`,
        parseCodeOptions,
        { signal: generation.current.signal },
      );
      if (!generation.current.signal.aborted) {
        setOptions(value);
        setNewOpen(true);
      }
    } catch (e) {
      if (!generation.current.signal.aborted) setError(codeError(e, onSessionEnd));
    } finally {
      if (!generation.current.signal.aborted) setLoading(false);
    }
  }
  function add(row: PageChangeRecord) {
    onChange([row, ...rows]);
    choose(row.id);
    setNewOpen(false);
    setImportOpen(false);
    setChat(false);
    setNotice('记录已保存到当前项目，后台任务和历史可刷新查看。');
  }
  const all = record ? changeItems(record, tab) : [],
    filtered = all.filter(
      (x) =>
        (!functionFilter || x.function === functionFilter) &&
        (!causeFilter || x.cause === causeFilter) &&
        (!handlingFilter ||
          (record?.handling[x.key]?.at(-1)?.status ||
            (tab === 'regressions' ? '待审阅' : '待处理')) === handlingFilter),
    ),
    pages = Math.max(1, Math.ceil(filtered.length / 10)),
    currentPage = Math.min(page, pages),
    visible = filtered.slice((currentPage - 1) * 10, currentPage * 10),
    item =
      record && detail ? changeItems(record, detail.tab).find((x) => x.key === detail.key) : null;
  const nav = (
    <aside className="panel code-analysis-records">
      <div className="panel-head">
        <h2>分析记录</h2>
        <span className="badge">{rows.length}</span>
      </div>
      <label className="form-field change-record-search">
        搜索记录
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="名称或版本"
        />
      </label>
      {rows
        .filter((x) =>
          (x.title + x.pairs.map((p) => p.before + p.after).join(''))
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .map((x) => (
          <div className="analysis-record-row" key={x.id}>
            <button
              className={`code-record ${record?.id === x.id ? 'active' : ''}`}
              aria-current={record?.id === x.id ? 'true' : undefined}
              onClick={() => choose(x.id)}
            >
              <strong>{x.title}</strong>
              <small>
                {changeModes[x.mode]} · {status(x)}
              </small>
              {x.pairs.map((p, i) => (
                <small key={i}>
                  旧：{p.before}
                  <br />
                  新：{p.after}
                </small>
              ))}
              <small>{new Date(x.createdAt).toLocaleString()}</small>
            </button>
            {project && (
              <AnalysisRecordDelete
                base={base}
                id={x.id}
                projectId={project.id}
                iconOnly
                recordTitle={x.title}
                canDelete={
                  user.platform_role === 'ADMIN' || project.can_manage || x.actorId === user.id
                }
                refreshKey={`${x.status}:${x.revision}`}
                onDeleted={onRecordDeleted}
                onSessionEnd={onSessionEnd}
              />
            )}
          </div>
        ))}
      {hasMore && (
        <button className="small panel-pad" onClick={() => void moreRecords()}>
          加载更多记录
        </button>
      )}
      {!rows.length && <p className="hint panel-pad">暂无变更分析记录。</p>}
    </aside>
  );
  return (
    <div className="code-analysis-page requirement-ui change-analysis-page">
      <header className="page-head">
        <div>
          <h1>{chat ? '变更分析对话' : '变更分析'}</h1>
        </div>
        <div className="head-actions">
          {chat ? (
            <button className="ghost" onClick={() => setChat(false)}>
              返回变更分析
            </button>
          ) : (
            <>
              <button
                className="primary"
                disabled={!project || loading}
                onClick={() => void openNew()}
              >
                <Icon name="branch" />
                {loading ? '加载来源…' : '新建变更分析'}
              </button>
              <button className="ghost" disabled={!project} onClick={() => setImportOpen(true)}>
                导入分析结果
              </button>
              <button
                className="ghost"
                disabled={!project}
                onClick={() => {
                  setChat(true);
                  setReference('');
                }}
              >
                历史对话
              </button>
            </>
          )}
        </div>
      </header>

      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {!project ? (
        <section className="panel panel-pad">
          <h2>请先选择项目</h2>
        </section>
      ) : (
        <>
          {!chat && (
            <section className="panel code-analysis-overview">
              <div>
                <span className="eyebrow">
                  {record ? changeModes[record.mode] : '固定版本比较'}
                </span>
                <h2>{record?.title || '暂无变更分析'}</h2>
                <p>
                  <AIConfigurationSummary value={record?.ai} />
                </p>

                <p className="hint">
                  {record
                    ? `${record.pairs.map((p) => p.before).join(' / ')} → ${record.pairs.map((p) => p.after).join(' / ')}`
                    : '选择旧基准 → 选择新目标'}
                </p>
                {record && (
                  <>
                    <span className="badge orange">{status(record)}</span>
                    {record.summary && <p>{record.summary}</p>}
                    {record.error_code && (
                      <p className="form-error">
                        {changeError(new Error(record.error_code), onSessionEnd)}
                      </p>
                    )}
                    {record.batches && (
                      <details className="evidence mt">
                        <summary>
                          历史分批进度：已完成 {record.batches.completed}/{record.batches.total} 批
                          {record.batches.failed > 0 && ` · 失败 ${record.batches.failed} 批`}
                        </summary>
                        <p className="hint">
                          历史批次，仅供查看。
                          {record.batches.version === 2 &&
                            ` · 关联复核 ${record.batches.review_batches || 0} 批`}
                        </p>
                        <div className="change-batch-list">
                          {record.batches.batches.map((batch) => (
                            <details className="hint" key={batch.id}>
                              <summary>
                                第 {batch.id} 批
                                {batch.kind &&
                                  ` · ${batch.kind === 'INTEGRATION' ? '关联复核' : '文件分析'}`}{' '}
                                ·{' '}
                                {batch.callable === false
                                  ? '依据未配对，未调用AI'
                                  : batch.error_code === 'change_batch_dependencies_pending'
                                    ? '等待前置批次，未调用AI'
                                    : ['FAILED', 'CANCELLED', 'COMPLETED'].includes(
                                          record.status || '',
                                        ) && ['QUEUED', 'RUNNING'].includes(batch.status)
                                      ? '已停止，尚未完成'
                                      : changeStates[batch.status]}
                                {' · '}
                                {Math.ceil(batch.input_bytes / 1024)} KB 固定文本（附件另计）
                                {batch.error_code &&
                                  ` · ${changeError(new Error(batch.error_code), onSessionEnd)}`}
                              </summary>
                              {!!batch.depends_on?.length && (
                                <p className="hint">原前置批次：{batch.depends_on.join('、')}。</p>
                              )}
                              {!!batch.blocked_targets?.length && (
                                <p className="hint">
                                  未核查目标：
                                  {batch.blocked_targets
                                    .map((target) => changeTargets[target] || target)
                                    .join('、')}
                                  。{batch.callable === false && '该历史批次未产生模型调用。'}
                                </p>
                              )}
                              {batch.blocking_reason && (
                                <p className="hint">{batch.blocking_reason}</p>
                              )}
                              {batch.oversized && (
                                <p className="hint">
                                  原完整关联证据包超过当时单批建议大小，正文未裁剪。
                                </p>
                              )}
                              {batch.files.map((file) => (
                                <p className="mono" key={file}>
                                  {file}
                                </p>
                              ))}
                            </details>
                          ))}
                        </div>
                      </details>
                    )}
                    <div className="row mt">
                      {record.can_cancel && (
                        <button
                          className="small"
                          disabled={actionBusy}
                          onClick={() => void operate('cancel')}
                        >
                          取消分析
                        </button>
                      )}
                      {record.can_retry && (
                        <button
                          className="small"
                          disabled={actionBusy}
                          onClick={() => void operate('retry', { request_id: crypto.randomUUID() })}
                        >
                          {record.retry_replan || record.batches
                            ? '完整输入重新分析（1次调用）'
                            : '重试'}
                        </button>
                      )}
                      {record.candidate_available && !record.batches && (
                        <AnalysisCandidateReview
                          endpoint={`${base}/${record.id}/candidate-review`}
                          onSessionEnd={onSessionEnd}
                        />
                      )}
                      {record.candidate_available && (
                        <button className="small" onClick={() => void exportRecord('candidate')}>
                          下载AI原始候选
                        </button>
                      )}
                      {record.can_revalidate && (
                        <button
                          className="small"
                          disabled={actionBusy}
                          onClick={() => void operate('revalidate')}
                        >
                          重新校验（不调用AI）
                        </button>
                      )}
                    </div>
                    {record.can_retry && (
                      <p className="hint">
                        {record.retry_replan || record.batches
                          ? '原分批成果和人工处理保留在原记录；新记录使用完整固定输入一次重新分析，不复用旧批次结论。'
                          : record.retry_preparation
                            ? '沿用原选择重新准备双侧输入；固定提交和资料版本保持，动态链接正文将重新读取。'
                            : '沿用已固定输入重试。'}
                        使用你的当前AI配置创建新任务，原失败记录保留。
                      </p>
                    )}
                  </>
                )}
              </div>
              <div className="code-analysis-stats">
                {(['changes', 'impacts'] as ChangeTab[]).map((key) => (
                  <span key={key}>
                    <strong>
                      {record?.status === 'COMPLETED' && record.loaded
                        ? changeItems(record, key).length
                        : '—'}
                    </strong>
                    <small>{changeTabs[key]}</small>
                  </span>
                ))}
                <span>
                  <strong>
                    {record?.status === 'COMPLETED' && record.loaded
                      ? record.impacts.filter((x) => x.cause === 'introduced').length
                      : '—'}
                  </strong>
                  <small>本次引入</small>
                </span>
                <span>
                  <strong>
                    {record?.status === 'COMPLETED' && record.loaded
                      ? changeItems(record, 'regressions').length
                      : '—'}
                  </strong>
                  <small>建议回归</small>
                </span>
              </div>
            </section>
          )}
          {!chat && project && record && (
            <AcceptancePanel
              projectId={project.id}
              module="changes"
              refreshKey={record.revision}
              recordId={Number(record.id)}
              onSessionEnd={onSessionEnd}
            />
          )}
          <div className={chat ? 'code-chat-layout' : 'code-analysis-workspace'}>
            {nav}
            {chat ? (
              record ? (
                <ChangeAnalysisChat
                  key={record.id}
                  record={record}
                  findingKey={reference}
                  onClearFinding={() => setReference('')}
                  onSessionEnd={onSessionEnd}
                />
              ) : (
                <section className="panel panel-pad">请先选择已完成记录。</section>
              )
            ) : (
              <section className="panel change-results">
                <div className="panel-head">
                  <div>
                    <h2>本次变更结果</h2>
                  </div>
                  <button
                    className="ghost small"
                    disabled={!record || record.status !== 'COMPLETED' || !record.loaded}
                    onClick={() => setExporting(true)}
                  >
                    导出完整记录
                  </button>
                </div>
                <div className="tabs change-result-tabs" role="tablist" aria-label="变更结果">
                  {(Object.entries(changeTabs) as [ChangeTab, string][]).map(
                    ([key, name], i, entries) => (
                      <button
                        id={`change-tab-${key}`}
                        key={key}
                        role="tab"
                        aria-controls="change-results"
                        aria-selected={tab === key}
                        tabIndex={tab === key ? 0 : -1}
                        className={tab === key ? 'selected' : ''}
                        onClick={() => {
                          setTab(key);
                          resetFilters();
                        }}
                        onKeyDown={(e) => {
                          if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
                          e.preventDefault();
                          const next =
                            e.key === 'Home'
                              ? 0
                              : e.key === 'End'
                                ? 2
                                : (i + (e.key === 'ArrowRight' ? 1 : 2)) % 3;
                          setTab(entries[next][0]);
                          resetFilters();
                          document.getElementById(`change-tab-${entries[next][0]}`)?.focus();
                        }}
                      >
                        {name}{' '}
                        {record?.status === 'COMPLETED' && record.loaded
                          ? changeItems(record, key).length
                          : ''}
                      </button>
                    ),
                  )}
                </div>
                <div className="code-filters">
                  <FormSelect
                    label="功能"
                    value={functionFilter}
                    options={[
                      { value: '', label: '全部功能' },
                      ...[...new Set(all.map((x) => x.function).filter(Boolean))].map((x) => ({
                        value: x,
                        label: x,
                      })),
                    ]}
                    onChange={(v) => {
                      setFunctionFilter(v);
                      setPage(1);
                    }}
                  />
                  {tab === 'impacts' && (
                    <FormSelect
                      label="归因"
                      value={causeFilter}
                      options={[
                        { value: '', label: '全部归因' },
                        ...Object.entries(changeCauses).map(([value, label]) => ({ value, label })),
                      ]}
                      onChange={(v) => {
                        setCauseFilter(v);
                        setPage(1);
                      }}
                    />
                  )}
                  {tab !== 'changes' && (
                    <FormSelect
                      label="处理"
                      value={handlingFilter}
                      options={[
                        { value: '', label: '全部状态' },
                        ...(tab === 'regressions'
                          ? ['待审阅', '采纳', '暂缓', '不采纳']
                          : ['待处理', '已确认', '已处理', '误报', '需补充证据']
                        ).map((x) => ({ value: x, label: x })),
                      ]}
                      onChange={(v) => {
                        setHandlingFilter(v);
                        setPage(1);
                      }}
                    />
                  )}
                </div>
                <div id="change-results" role="tabpanel" aria-labelledby={`change-tab-${tab}`}>
                  {visible.map((x) => (
                    <article className="code-finding" key={x.key}>
                      <div className="row">
                        <span className="mono muted">{x.key}</span>
                        <span className="badge">{x.function || '待归类'}</span>
                        {x.kind && <span className="badge">{x.kind}</span>}
                        {x.cause && (
                          <span className={`badge ${x.cause === 'introduced' ? 'red' : 'orange'}`}>
                            {changeCauses[x.cause as keyof typeof changeCauses]}
                          </span>
                        )}
                        {x.severity && (
                          <span className={`badge ${x.severity === '高' ? 'red' : 'orange'}`}>
                            {x.severity}风险
                          </span>
                        )}
                        {x.evidence && <span className="badge">{x.evidence}</span>}
                        {tab === 'regressions' && x.priority && (
                          <span className="badge orange">{x.priority}</span>
                        )}
                        {tab !== 'changes' && (
                          <span
                            className={`badge ${record?.handling[x.key]?.at(-1)?.status === '采纳' ? 'green' : ''}`}
                          >
                            {record?.handling[x.key]?.at(-1)?.status ||
                              (tab === 'regressions' ? '待审阅' : '待处理')}
                          </span>
                        )}
                      </div>
                      <h3>{x.title}</h3>
                      <p>{x.text}</p>
                      {tab === 'changes' && x.location && <p className="hint mono">{x.location}</p>}
                      {tab === 'regressions' ? (
                        <div className="evidence">
                          <strong>{x.caseRef || '未提供用例版本'}</strong>
                          <p>
                            {x.priority} · {x.suggested} · {x.expected}
                          </p>
                        </div>
                      ) : (
                        tab === 'impacts' && (
                          <div className="code-finding-chain">
                            {[
                              x.directness,
                              x.certainty,
                              x.change_keys.length ? `关联 ${x.change_keys.join('、')}` : '',
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </div>
                        )
                      )}
                      <div className="between mt">
                        <span className="hint">
                          {tab === 'changes'
                            ? '固定双侧证据'
                            : record?.handling[x.key]?.at(-1)?.status ||
                              (tab === 'regressions' ? '待审阅' : '待处理')}{' '}
                          · 项目内保存
                        </span>
                        <button className="link" onClick={() => setDetail({ tab, key: x.key })}>
                          查看详情 →
                        </button>
                      </div>
                    </article>
                  ))}
                  {!visible.length && (
                    <div className="empty">
                      <h3>
                        {!record
                          ? '暂无变更记录'
                          : !record.loaded
                            ? '正在加载固定记录…'
                            : record.status !== 'COMPLETED'
                              ? '后台任务尚未完成'
                              : '当前范围没有匹配结果'}
                      </h3>
                      <p className="hint">
                        {record && record.status !== 'COMPLETED'
                          ? '当前任务尚无结果。'
                          : '可以新建分析或导入已有结果；没有条目不代表无影响。'}
                      </p>
                    </div>
                  )}
                </div>
                {!!filtered.length && (
                  <nav className="code-analysis-pagination between" aria-label="变更结果分页">
                    <span className="hint">
                      {filtered.length}条 · 每页10条 · 第{currentPage}/{pages}页
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
                )}
              </section>
            )}
            <ChangeScope record={record} onCompare={() => setCompare(true)} />
          </div>
        </>
      )}
      {project && newOpen && options && (
        <ChangeAnalysisNew
          projectId={project.id}
          user={user}
          options={options}
          onSessionEnd={onSessionEnd}
          onClose={() => setNewOpen(false)}
          onCreate={add}
        />
      )}
      {project && importOpen && (
        <ChangeImport
          projectId={project.id}
          onClose={() => setImportOpen(false)}
          onImported={add}
          onSessionEnd={onSessionEnd}
        />
      )}
      {record && item && detail && (
        <ChangeDetail
          key={`${record.id}:${item.key}`}
          record={record}
          item={item}
          tab={detail.tab}
          onClose={() => setDetail(null)}
          onAsk={() => {
            setReference(item.key);
            setChat(true);
            setDetail(null);
          }}
          onSave={(state, note) =>
            void operate('handling', {
              revision: record.revision,
              item_key: item.key,
              status:
                state === '待审阅' || state === '待处理'
                  ? 'PENDING'
                  : Object.keys(handlingStates).find((key) => handlingStates[key] === state),
              note,
            })
          }
          busy={actionBusy}
        />
      )}
      {record && compare && (
        <CaseDialog title="固定新旧对照" busy={false} wide onClose={() => setCompare(false)}>
          <p className="notice">
            {record.status !== 'COMPLETED'
              ? '当前任务未完成，以下仅显示已固定范围。'
              : '导入快照尚未与真实仓库比对。'}
          </p>
          {record.pairs.map((p, i) => (
            <section className="evidence" key={i}>
              <strong>{p.name}</strong>
              <p className="mono">
                {p.before} → {p.after}
              </p>
              <p>{p.update}</p>
            </section>
          ))}
          {changeItems(record, 'changes').map((x) => (
            <section key={x.key}>
              <h3 className="mt">
                {x.key} · {x.title}
              </h3>
              <Evidence item={x} />
            </section>
          ))}
        </CaseDialog>
      )}
      {record && exporting && (
        <CaseDialog title="导出完整变更记录" busy={false} onClose={() => setExporting(false)}>
          <p className="hint">导出当前记录的全部结果与人工处理，不受筛选限制。</p>
          <div className="row mt">
            <button className="primary" onClick={() => void exportRecord('markdown')}>
              Markdown
            </button>
            <button disabled={!record.inputText} onClick={() => void exportRecord('input')}>
              input.json
            </button>
            <button disabled={!record.reportText} onClick={() => void exportRecord('report')}>
              report.json
            </button>
          </div>
        </CaseDialog>
      )}
    </div>
  );
}
function ChangeDetail({
  record,
  item,
  tab,
  onClose,
  onAsk,
  onSave,
  busy,
}: {
  record: PageChangeRecord;
  item: ChangeItem;
  tab: ChangeTab;
  onClose: () => void;
  onAsk: () => void;
  onSave: (status: string, note: string) => void;
  busy: boolean;
}) {
  const history = record.handling[item.key] || [],
    latest = history.at(-1),
    initial = tab === 'regressions' ? '待审阅' : '待处理',
    [state, setState] = useState(latest?.status || initial),
    [note, setNote] = useState(latest?.note || ''),
    [error, setError] = useState('');
  const formId = useId();
  return (
    <CaseDialog
      title={`${item.key} · ${item.title}`}
      busy={busy}
      onClose={onClose}
      wide
      className="code-analysis-dialog change-analysis-dialog"
      footer={
        <footer className="change-dialog-footer">
          <button type="button" onClick={onClose}>
            关闭
          </button>
          <button type="button" className="ghost" onClick={onAsk}>
            引用追问
          </button>
          {tab !== 'changes' && (
            <button type="submit" form={formId} className="primary" disabled={busy}>
              保存{tab === 'regressions' ? '审阅' : '处理'}
            </button>
          )}
        </footer>
      }
    >
      <div className="row change-detail-badges">
        <span className="badge blue">{changeTabs[tab]}</span>
        {item.cause && (
          <span className={`badge ${item.cause === 'introduced' ? 'red' : 'orange'}`}>
            {changeCauses[item.cause as keyof typeof changeCauses]}
          </span>
        )}
        {item.evidence && <span className="badge">{item.evidence}</span>}
        {item.severity && (
          <span className={`badge ${item.severity === '高' ? 'red' : 'orange'}`}>
            {item.severity}风险
          </span>
        )}
        {tab !== 'changes' && <span className="badge">{state}</span>}
      </div>
      <h3 className="mt">{tab === 'regressions' ? '推荐原因' : '业务说明'}</h3>
      <p className="smalltext">{item.text}</p>
      {item.details?.map((value, i) => (
        <section className="evidence mt" key={i}>
          <strong>{value.label}</strong>
          <p className="preserve-lines">{value.text}</p>
        </section>
      ))}

      {tab === 'regressions' ? (
        <>
          <div className="evidence">
            <strong>固定用例与建议动作</strong>
            <p>
              {item.caseRef} · {item.suggested} · {item.priority}
            </p>
            <p className="hint">保留设计的用例仍可纳入回归。</p>
          </div>
          <div className="evidence">
            <strong>前置条件与数据</strong>
            <p>{item.data}</p>
            <strong>操作</strong>
            <p>{item.action}</p>
            <strong>应核对结果</strong>
            <p>{item.expected}</p>
          </div>
        </>
      ) : (
        <Evidence item={item} />
      )}
      {item.chain.length > 0 && (
        <>
          <h3 className="mt">影响链 · 用户提供的节点</h3>
          {item.chain.map((x, i) => (
            <p className="evidence mono" key={i}>
              {x}
            </p>
          ))}
        </>
      )}
      {item.attribution && (
        <>
          <h3 className="mt">归因依据</h3>
          <p>{item.attribution}</p>
        </>
      )}
      {item.missing.length > 0 && (
        <>
          <h3 className="mt">待补证据</h3>
          {item.missing.map((x, i) => (
            <p key={i}>{x}</p>
          ))}
        </>
      )}
      {(item.suggestion || item.verification) && (
        <div className="form-grid">
          <section className="evidence">
            <strong>修复／完善建议</strong>
            <p>{item.suggestion}</p>
          </section>
          <section className="evidence">
            <strong>验证建议</strong>
            <p>{item.verification}</p>
          </section>
        </div>
      )}
      {tab !== 'changes' && (
        <Form
          id={formId}
          className="evidence change-handling-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (state !== initial && !note.trim()) {
              setError('非默认状态请填写依据或处理说明。');
              return;
            }
            onSave(state, note.trim());
          }}
        >
          <h3>人工{tab === 'regressions' ? '审阅' : '处理'}</h3>
          <div className="form-grid mt">
            <FormSelect
              label="状态"
              value={state}
              options={(tab === 'regressions'
                ? ['待审阅', '采纳', '暂缓', '不采纳']
                : ['待处理', '已确认', '已处理', '误报', '需补充证据']
              ).map((x) => ({ value: x, label: x }))}
              onChange={setState}
            />
            <label className="form-field">
              处理说明
              <textarea
                maxLength={4000}
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </label>
          </div>
          <p className="hint">仅采纳回归范围，不执行测试。</p>
          {history.map((h, i) => (
            <p className="hint" key={i}>
              {h.time} · {h.status}：{h.note}
            </p>
          ))}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </Form>
      )}
    </CaseDialog>
  );
}
