import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import type { Project } from './Projects';
import { Icon } from './Icon';
import { CaseDialog } from './CaseDialog';
import { PageJump } from './PageJump';
import {
  overviewError,
  overviewFilters,
  overviewHref,
  overviewModules,
  overviewStates,
  readAttention,
  readOverview,
} from './overviewApi';
import type {
  AttentionPage,
  AttentionPart,
  OverviewFilter,
  OverviewModule,
  OverviewRecord,
  OverviewSummary,
} from './overviewApi';
import './project-overview.css';

const time = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false });
export function ProjectOverview({
  project,
  onSessionEnd,
}: {
  project: Project | null;
  onSessionEnd: () => void;
}) {
  const navigate = useNavigate(),
    [search, setSearch] = useSearchParams();
  const requested = search.get('view') || 'all';
  const filter: OverviewFilter = Object.hasOwn(overviewFilters, requested)
    ? (requested as OverviewFilter)
    : 'all';
  const [data, setData] = useState<OverviewSummary | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0);
  const [selection, setSelection] = useState<{
      module: OverviewModule;
      part: AttentionPart;
    } | null>(null),
    [choicePage, setChoicePage] = useState(1),
    [choices, setChoices] = useState<AttentionPage | null>(null),
    [choiceLoading, setChoiceLoading] = useState(false),
    [choiceError, setChoiceError] = useState('');
  const current = useRef(data),
    recentPanel = useRef<HTMLElement>(null),
    recordList = useRef<HTMLDivElement>(null),
    tabs = useRef<(HTMLButtonElement | null)[]>([]);
  current.current = data;
  useEffect(() => {
    if (!project) {
      setLoading(false);
      return;
    }
    const c = new AbortController();
    let fetching = false;
    async function read() {
      if (fetching || c.signal.aborted) return;
      fetching = true;
      setLoading(true);
      try {
        const next = await readOverview(project!.id, filter, c.signal);
        if (!c.signal.aborted) {
          setData(next);
          setError('');
        }
      } catch (e) {
        if (!c.signal.aborted) {
          if (
            e instanceof Error &&
            ['not_authenticated', 'project_not_found'].includes(e.message)
          ) {
            setData(null);
            setSelection(null);
            setChoices(null);
          }
          setError(overviewError(e, onSessionEnd));
        }
      } finally {
        fetching = false;
        if (!c.signal.aborted) setLoading(false);
      }
    }
    const visible = () => {
      if (document.visibilityState === 'visible') void read();
    };
    void read();
    const timer = setInterval(() => {
      if (
        document.visibilityState === 'visible' &&
        (current.current?.counts.queued || 0) + (current.current?.counts.running || 0) > 0
      )
        void read();
    }, 10000);
    window.addEventListener('focus', visible);
    document.addEventListener('visibilitychange', visible);
    return () => {
      c.abort();
      clearInterval(timer);
      window.removeEventListener('focus', visible);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [project, filter, reload, onSessionEnd]);
  useEffect(() => {
    if (!project || !selection) return;
    const c = new AbortController();
    setChoiceLoading(true);
    setChoiceError('');
    setChoices(null);
    void readAttention(project.id, selection.module, selection.part, choicePage, c.signal)
      .then((value) => {
        if (c.signal.aborted) return;
        if (value.total > 0 && choicePage > Math.ceil(value.total / 20)) {
          setChoicePage(Math.ceil(value.total / 20));
          return;
        }
        if (choicePage === 1 && value.total === 1 && value.items[0]) {
          navigate(overviewHref(project.id, value.items[0], selection.part));
          return;
        }
        setChoices(value);
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          if (e instanceof Error && ['not_authenticated', 'project_not_found'].includes(e.message))
            setData(null);
          setChoiceError(overviewError(e, onSessionEnd));
        }
      })
      .finally(() => {
        if (!c.signal.aborted) setChoiceLoading(false);
      });
    return () => c.abort();
  }, [project, selection, choicePage, navigate, onSessionEnd]);
  function chooseFilter(value: OverviewFilter) {
    recordList.current?.scrollTo({ top: 0 });
    setSearch(value === 'all' ? {} : { view: value });
  }
  if (!project)
    return (
      <section className="panel panel-pad">
        <h1>项目概览</h1>
        <p>请先选择项目。</p>
      </section>
    );
  const summary = data?.project_id === project.id ? data : null;
  const unknown = summary?.counts.queued === null || summary?.counts.running === null;
  const active = summary ? (summary.counts.queued || 0) + (summary.counts.running || 0) : null;
  const card = (
    label: string,
    value: number | string | null,
    unit: string,
    note: string,
    action: () => void,
  ) => (
    <button type="button" className="panel ov-stat" disabled={!summary && loading} onClick={action}>
      <span className="ov-stat-title">
        {label}
        <Icon name="arrow" />
      </span>
      <span className="ov-stat-value">
        {value ?? '—'}
        <small>{value !== null && unit}</small>
      </span>
      <span className="hint">{note}</span>
    </button>
  );
  const records = summary?.filter === filter ? summary.recent : [];
  return (
    <div className="ov-page">
      <div className="page-head">
        <div>
          <h1>项目概览</h1>
        </div>
        <div className="row">
          <button className="ghost" disabled={loading} onClick={() => setReload((v) => v + 1)}>
            {loading ? '更新中…' : '刷新'}
          </button>
          <Link className="action ghost" to="/project">
            项目设置
          </Link>
        </div>
      </div>
      <section className="ov-project">
        <div>
          <h2>{project.name}</h2>
          <p className="hint">{project.identifier}</p>
          <p>{project.description || '暂无项目说明'}</p>
        </div>
        <p className="hint">
          {summary ? `更新于 ${time(summary.as_of)}` : loading ? '正在读取…' : '尚未读取'}
        </p>
      </section>
      {error && (
        <p className="form-error" role="alert">
          {error}
          {summary && ' 显示上次成功读取的数据。'}{' '}
          <button className="link" onClick={() => setReload((v) => v + 1)}>
            重新读取
          </button>
        </p>
      )}
      {summary?.unavailable.length ? (
        <p className="notice" role="status">
          部分模块暂不可用，相应数量显示“—”。
        </p>
      ) : null}
      <div className="ov-stats" aria-busy={loading}>
        {card(
          '需求资料',
          summary?.counts.requirements ?? null,
          '份',
          '按当前来源计数，不累计版本',
          () => navigate('/documents'),
        )}
        {card('原型资料', summary?.counts.prototypes ?? null, '个', '仓库和链接各算一个来源', () =>
          navigate('/prototypes'),
        )}
        {card('活动用例', summary?.counts.cases ?? null, '条', '不含停用及已删除用例', () =>
          navigate('/cases'),
        )}
        {card(
          '执行中',
          unknown ? '暂不可用' : active,
          unknown ? '' : '条',
          unknown
            ? '部分模块读取失败'
            : summary
              ? `排队 ${summary.counts.queued} · 分析中 ${summary.counts.running}`
              : '正在读取主分析状态',
          () => {
            chooseFilter('running');
            recentPanel.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          },
        )}
      </div>
      <section className="panel ov-shortcuts">
        <div>
          <h2>分析入口</h2>
        </div>
        <div className="ov-shortcut-buttons">
          {Object.entries(overviewModules).map(([key, [name, path, icon]]) => (
            <Link key={key} className="action ghost" to={path}>
              <Icon name={icon} />
              {name}
            </Link>
          ))}
        </div>
      </section>
      <div className="ov-content">
        <section className="panel ov-recent" id="overview-recent" tabIndex={-1} ref={recentPanel}>
          <div className="panel-head">
            <div>
              <h2>近期分析</h2>
            </div>
            <span className="ov-list-count">
              {loading && !summary ? '读取中' : `${records.length} 条记录`}
            </span>
          </div>
          <div className="ov-recent-toolbar">
            <div className="ov-tabs" role="tablist" aria-label="近期分析筛选">
              {Object.entries(overviewFilters).map(([key, name], i, entries) => (
                <button
                  key={key}
                  id={`overview-tab-${key}`}
                  type="button"
                  role="tab"
                  aria-controls="overview-panel"
                  aria-selected={filter === key}
                  tabIndex={filter === key ? 0 : -1}
                  ref={(node) => {
                    tabs.current[i] = node;
                  }}
                  onClick={() => chooseFilter(key as OverviewFilter)}
                  onKeyDown={(e) => {
                    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
                    e.preventDefault();
                    const n =
                      e.key === 'Home'
                        ? 0
                        : e.key === 'End'
                          ? entries.length - 1
                          : (i + (e.key === 'ArrowRight' ? 1 : entries.length - 1)) %
                            entries.length;
                    chooseFilter(entries[n][0] as OverviewFilter);
                    tabs.current[n]?.focus();
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>
          <div
            className="ov-record-list"
            ref={recordList}
            role="tabpanel"
            id="overview-panel"
            aria-labelledby={`overview-tab-${filter}`}
            aria-describedby="overview-recent-help"
            aria-busy={loading}
            tabIndex={0}
          >
            {loading && !records.length ? (
              <p className="panel-pad" role="status">
                正在读取分析记录…
              </p>
            ) : (
              records.map((r) => (
                <OverviewRecordCard
                  key={`${r.module}:${r.record_type}:${r.record_id}`}
                  projectId={project.id}
                  record={r}
                />
              ))
            )}
            {!loading && !records.length && !error && (
              <div className="ov-recent-empty">
                <span className="ov-empty-icon">
                  <Icon name="clock" />
                </span>
                <h3>
                  {summary?.unavailable.length
                    ? '部分模块不可用，暂无可展示的记录'
                    : filter === 'all'
                      ? '还没有分析记录'
                      : '当前筛选没有匹配记录'}
                </h3>
              </div>
            )}
          </div>
          <div className="ov-recent-footnote" id="overview-recent-help">
            每类最多8条，完整历史见对应模块
          </div>
        </section>
        <aside className="panel ov-attention">
          <div className="panel-head">
            <div>
              <h2>需要关注</h2>
              <p className="hint">历史累计，可能包含重复发现</p>
            </div>
          </div>
          {!summary && (
            <p className="panel-pad" role="status">
              {loading ? '正在读取关注事项…' : '关注摘要尚未读取。'}
            </p>
          )}
          {summary?.attention.map((group) => (
            <section className="ov-attention-group" key={group.module}>
              <div className="between">
                <h3>{overviewModules[group.module][0]}</h3>
                <Link className="smalltext" to={overviewModules[group.module][1]}>
                  进入模块
                </Link>
              </div>
              <div className="ov-attention-parts">
                {group.parts.map((part) => (
                  <button
                    key={`${part.group}:${part.state}`}
                    type="button"
                    className={`ov-attention-chip${part.count && part.count > 0 ? ' has-pending' : ''}`}
                    disabled={!part.count}
                    onClick={() => {
                      setChoicePage(1);
                      setChoices(null);
                      setSelection({ module: group.module, part });
                    }}
                  >
                    <span>{part.label}</span>
                    <strong>
                      {part.count ?? '暂不可用'}
                      <small>
                        {part.count !== null && (group.module === 'generate' ? '条记录' : '项')}
                      </small>
                    </strong>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </aside>
      </div>
      {selection && (
        <CaseDialog
          title="选择需要查看的记录"
          busy={false}
          onClose={() => setSelection(null)}
          wide
          className="ov-choice-dialog"
          footer={
            <footer className="ov-choice-footer">
              {choices && choices.total > 20 && (
                <div className="between ov-choice-pagination">
                  <span>共{choices.total}条</span>
                  <div className="row">
                    <button
                      disabled={choiceLoading || choicePage === 1}
                      onClick={() => setChoicePage((v) => v - 1)}
                    >
                      上一页
                    </button>
                    <button
                      disabled={choiceLoading || choicePage * 20 >= choices.total}
                      onClick={() => setChoicePage((v) => v + 1)}
                    >
                      下一页
                    </button>
                    <PageJump
                      page={choicePage}
                      pages={Math.ceil(choices.total / 20)}
                      disabled={choiceLoading}
                      onChange={setChoicePage}
                    />
                  </div>
                </div>
              )}
              <div className="row">
                <button onClick={() => setSelection(null)}>关闭</button>
              </div>
            </footer>
          }
        >
          <p className="hint">
            {overviewModules[selection.module][0]} · {selection.part.label}
          </p>
          {choiceError && (
            <p className="form-error" role="alert">
              {choiceError}
              <button onClick={() => setSelection({ ...selection })}>重新读取</button>
            </p>
          )}
          {choiceLoading && <p role="status">正在读取记录…</p>}
          <div className="ov-choice-list">
            {choices?.items.map((r) => (
              <div className="ov-choice" key={`${r.record_type}:${r.record_id}`}>
                <div>
                  <strong>{r.title || `${overviewModules[r.module][0]} ${r.record_id}`}</strong>
                  <p className="hint">
                    {r.record_id} · {time(r.created_at)}
                  </p>
                </div>
                <Link className="action small" to={overviewHref(project.id, r, selection.part)}>
                  查看
                </Link>
              </div>
            ))}
          </div>
          {!choiceLoading && choices?.total === 0 && <p>这些事项已变化，请关闭后刷新概览。</p>}
        </CaseDialog>
      )}
    </div>
  );
}
function OverviewRecordCard({
  projectId,
  record: r,
}: {
  projectId: number;
  record: OverviewRecord;
}) {
  const [module, , icon] = overviewModules[r.module],
    status = overviewStates[r.status];
  return (
    <article className="ov-record" data-state={status}>
      <span className="ov-module-icon" aria-hidden="true">
        <Icon name={icon} />
      </span>
      <div className="ov-record-main">
        <div className="ov-record-module">
          {module}
          <span className="ov-record-id">#{r.record_id}</span>
        </div>
        <h3 className="ov-record-title">{r.title || `${module} · ${r.record_id}`}</h3>
        <div className="ov-record-meta">
          {time(r.created_at)} · {r.actor}
        </div>
        <div className="ov-record-status">
          {(r.status === 'COMPLETED' || r.outcome !== null) && r.outcome !== 'COMPLETE' && (
            <span
              className={`badge ${r.outcome === 'PARTIAL' || r.outcome === 'BLOCKED' ? 'orange' : ''}`}
            >
              {r.outcome === 'PARTIAL'
                ? '部分完成'
                : r.outcome === 'BLOCKED'
                  ? '依据不足'
                  : '完整性待查看'}
            </span>
          )}
          {r.application_failed && <span className="badge red">有入库失败项</span>}
        </div>
      </div>
      <div className="ov-record-actions">
        <span
          className="ov-record-state"
          data-state={status}
          aria-label={
            r.status === 'FAILED' ? '历史失败记录，查看记录可核对原因及重试关联' : undefined
          }
        >
          {r.imported ? '导入结果' : status}
        </span>
        <Link
          className="action ghost small ov-record-open"
          to={overviewHref(projectId, r)}
          aria-label={`查看记录：${module}，${r.title}`}
        >
          查看 <Icon name="arrow" />
        </Link>
      </div>
    </article>
  );
}
