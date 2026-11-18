import { PageJump } from './PageJump';
import { Form } from './Form';
import { Select } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import type { Project } from './Projects';
import { apiDownload, apiRequest } from './api/http';
import { Icon } from './Icon';
import { CaseDialog } from './CaseDialog';
import { CaseTableEditor } from './CaseTableEditor';
import { CaseEditor } from './CaseEditor';
import { CaseImportDialog } from './CaseImportDialog';
import {
  CASE_COLUMNS,
  caseError,
  caseListRequest,
  parseCaseList,
  parseCaseMetadata,
} from './caseApi';
import type {
  CaseCategory,
  CaseList,
  CaseSearch,
  CaseEditScope,
  CaseRow,
  Condition,
} from './caseApi';

const firstCondition = (): Condition => ({ field: 'title', operator: 'contains', value: '' });
export function Cases({
  project,
  onSessionEnd,
}: {
  project: Project | null;
  onSessionEnd: () => void;
}) {
  const base = `/api/projects/${project?.id}/cases`;
  const [data, setData] = useState<CaseList | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState<Condition[]>([firstCondition()]),
    [search, setSearch] = useState<CaseSearch>({
      page: 1,
      page_size: 10,
      category_id: null,
      conditions: [],
    }),
    [selected, setSelected] = useState<number[]>([]);
  const [modal, setModal] = useState<
      | 'manage'
      | 'category'
      | 'delete'
      | 'assign'
      | 'case'
      | 'import'
      | 'batch'
      | 'delete-case'
      | null
    >(null),
    [category, setCategory] = useState<CaseCategory | null>(null),
    [name, setName] = useState(''),
    [target, setTarget] = useState<number | null>(null),
    [caseId, setCaseId] = useState<number | null>(null),
    [modalError, setModalError] = useState('');
  const [editSession, setEditSession] = useState<{
    snapshot: CaseList;
    search: CaseEditScope;
    singleId: number | null;
    label: string;
  } | null>(null);
  const [editScope, setEditScope] = useState<'selected' | 'filtered' | 'project'>('filtered');
  const [deleting, setDeleting] = useState<CaseRow | null>(null);
  async function startBatch() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setModalError('');
    const scope: CaseEditScope =
      editScope !== 'filtered'
        ? { page: 1, page_size: 100, category_id: null, conditions: [] }
        : { ...search, page: 1, page_size: 100 };
    if (editScope === 'selected') scope.case_ids = [...selected];
    try {
      const snapshot = parseCaseList(
        await apiRequest<unknown>(`${base}/edit-scope`, {
          method: 'POST',
          body: JSON.stringify(scope),
          timeoutMs: 180000,
        }),
      );
      if (!alive.current) return;
      if (!snapshot.items.length) {
        setModalError('此范围没有用例。');
        return;
      }
      setEditSession({
        snapshot,
        search: scope,
        singleId: null,
        label:
          editScope === 'selected'
            ? `已勾选 ${selected.length} 条（跨页）`
            : editScope === 'project'
              ? '整个项目（全部分页）'
              : '当前筛选结果（全部分页）',
      });
      setModal(null);
    } catch (e) {
      if (alive.current) setModalError(caseError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const pending = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!project) {
      setLoading(false);
      return;
    }
    const c = new AbortController();
    setLoading(true);
    setError('');
    caseListRequest(base, search, c.signal)
      .then((value) => {
        if (!c.signal.aborted) {
          setData(value);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(caseError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [base, project, search, revision, onSessionEnd]);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  function reload(message = '') {
    setRevision((n) => n + 1);
    if (message) setNotice(message);
  }
  function openCategory(value: CaseCategory | null) {
    setCategory(value);
    setName(value?.name || '');
    setModalError('');
    setModal('category');
  }
  async function mutate(path: string, payload: Record<string, unknown>, method = 'POST') {
    if (!data || pending.current) return;
    pending.current = true;
    setBusy(true);
    setModalError('');
    try {
      const result = parseCaseMetadata(
        await apiRequest<unknown>(`${base}/${path}`, {
          method,
          body: JSON.stringify({ ...payload, revision: data.revision }),
        }),
      );
      if (alive.current) {
        setData({ ...data, ...result });
        setModal(null);
        setSelected([]);
        if (modal === 'delete' && search.category_id === category?.id)
          setSearch((q) => ({ ...q, page: 1, category_id: target }));
        reload('操作已保存。');
      }
    } catch (e) {
      if (alive.current) {
        const message = caseError(e, onSessionEnd);
        setError(message);
        setModalError(message);
      }
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function exportFile() {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const blob = await apiDownload(`${base}/export`, {
        method: 'POST',
        body: JSON.stringify(search),
        timeoutMs: 180000,
      });
      const url = URL.createObjectURL(blob),
        anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = '测试用例.xlsx';
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (alive.current) setError(caseError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const categoryName = (id: number | null) =>
    data?.categories.find((c) => c.id === id)?.name || '未分类';
  if (editSession)
    return (
      <CaseTableEditor
        base={base}
        snapshot={editSession.snapshot}
        search={editSession.search}
        singleId={editSession.singleId}
        scopeLabel={editSession.label}
        onClose={() => {
          setEditSession(null);
          reload();
        }}
        onSaved={(message) => {
          setEditSession(null);
          setSelected([]);
          reload(message);
        }}
        onSessionEnd={onSessionEnd}
      />
    );
  if (!project)
    return (
      <section className="panel panel-pad">
        <h2>请选择项目</h2>
      </section>
    );
  return (
    <section className="cases-page">
      <header className="page-head">
        <div>
          <h1>用例管理</h1>
        </div>
        <div className="row">
          <button
            disabled={busy || loading || !data}
            onClick={() => {
              setEditScope(selected.length ? 'selected' : 'filtered');
              setModalError('');
              setModal('batch');
            }}
          >
            <Icon name="edit" />
            批量编辑
          </button>
          <button disabled={busy || loading || !data} onClick={() => setModal('import')}>
            <Icon name="upload" />
            导入用例
          </button>
          <button disabled={busy || loading || !data} onClick={() => void exportFile()}>
            <Icon name="download" />
            导出 Excel
          </button>
          <button
            className="primary"
            disabled={busy || loading || !data}
            onClick={() => {
              setCaseId(null);
              setModal('case');
            }}
          >
            <Icon name="plus" />
            新建用例
          </button>
        </div>
      </header>

      {notice && (
        <p role="status" className="account-notice">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="doc-error">
          {error}
          <button disabled={busy || loading} onClick={() => reload()}>
            重新加载
          </button>
        </p>
      )}
      <section className="panel">
        <div className="case-category-toolbar">
          <label className="case-inline-label">
            生命周期
            <Select
              disabled={busy}
              value={search.lifecycle || 'ACTIVE'}
              onChange={(v) =>
                setSearch((q) => ({
                  ...q,
                  page: 1,
                  lifecycle: v === 'RETIRED' ? 'RETIRED' : v === 'ALL' ? 'ALL' : 'ACTIVE',
                }))
              }
            >
              <option value="ACTIVE">活动</option>
              <option value="RETIRED">停用</option>
              <option value="ALL">全部</option>
            </Select>
          </label>
          <label className="case-inline-label">
            用例分类
            <Select
              value={search.category_id ?? '*'}
              disabled={busy}
              onChange={(e) =>
                setSearch((q) => ({
                  ...q,
                  page: 1,
                  category_id: e === '*' ? null : Number(e),
                }))
              }
            >
              <option value="*">全部分类</option>
              <option value="0">未分类</option>
              {data?.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </label>
          <button
            className="small"
            disabled={!data || busy || loading}
            onClick={() => openCategory(null)}
          >
            <Icon name="plus" />
            创建分类
          </button>
          <button
            className="small"
            disabled={!data || busy || loading}
            onClick={() => {
              setModalError('');
              setModal('manage');
            }}
          >
            管理分类
          </button>
          <span className="case-selected-count">已选 {selected.length} 条</span>
          <button
            className="small"
            disabled={!selected.length || busy || loading}
            onClick={() => {
              setTarget(null);
              setModalError('');
              setModal('assign');
            }}
          >
            批量修改分类
          </button>
          <button className="ghost small" disabled={busy} onClick={() => setSelected([])}>
            清空选择
          </button>
        </div>
        <Form
          className="case-search-panel"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch((q) => ({ ...q, page: 1, conditions: draft.map((c) => ({ ...c })) }));
          }}
        >
          <div className="between">
            <strong>按表头字段搜索</strong>
            <span className="hint">多个条件同时满足</span>
          </div>
          {draft.map((q, i) => (
            <div className="case-query-row" key={i}>
              <Select
                aria-label={`搜索字段 ${i + 1}`}
                value={q.field}
                onChange={(e) =>
                  setDraft((rows) =>
                    rows.map((r, n) => (n === i ? { ...r, field: e as Condition['field'] } : r)),
                  )
                }
              >
                {CASE_COLUMNS.map(([k, n]) => (
                  <option key={k} value={k}>
                    {n}
                  </option>
                ))}
              </Select>
              <Select
                aria-label={`匹配方式 ${i + 1}`}
                value={q.operator}
                onChange={(e) =>
                  setDraft((rows) =>
                    rows.map((r, n) =>
                      n === i ? { ...r, operator: e as Condition['operator'] } : r,
                    ),
                  )
                }
              >
                <option value="contains">包含</option>
                <option value="equals">等于</option>
                <option value="notContains">不包含</option>
              </Select>
              <input
                aria-label={`搜索内容 ${i + 1}`}
                placeholder="输入搜索内容"
                value={q.value}
                onChange={(e) =>
                  setDraft((rows) =>
                    rows.map((r, n) => (n === i ? { ...r, value: e.target.value } : r)),
                  )
                }
              />
              <button
                type="button"
                className="ghost small"
                aria-label={`删除搜索条件 ${i + 1}`}
                onClick={() =>
                  setDraft((rows) =>
                    rows.length === 1 ? [firstCondition()] : rows.filter((_, n) => n !== i),
                  )
                }
              >
                <Icon name="trash" />
              </button>
            </div>
          ))}
          <div className="row">
            <button
              type="button"
              className="small"
              disabled={draft.length >= 20}
              onClick={() => setDraft((v) => [...v, { ...firstCondition(), field: 'module' }])}
            >
              <Icon name="plus" />
              添加条件
            </button>
            <button className="primary small" disabled={loading}>
              搜索
            </button>
            <button
              type="button"
              className="small"
              onClick={() => {
                setDraft([firstCondition()]);
                setSearch((q) => ({ ...q, page: 1, category_id: null, conditions: [] }));
              }}
            >
              重置
            </button>
          </div>
        </Form>
        <div
          className="case-table-scroll"
          tabIndex={0}
          aria-label="用例表格，可横向滚动查看14列"
          aria-busy={loading}
        >
          <table className="case-table">
            <thead>
              <tr>
                {CASE_COLUMNS.map(([key, name]) => (
                  <th key={key} scope="col">
                    {key === 'serial' ? (
                      <label className="case-check">
                        <input
                          type="checkbox"
                          aria-label="选择本页用例"
                          disabled={loading || busy || !data?.items.length}
                          checked={
                            !!data?.items.length && data.items.every((c) => selected.includes(c.id))
                          }
                          onChange={(e) => {
                            const ids = data?.items.map((c) => c.id) || [];
                            setSelected((old) =>
                              e.target.checked
                                ? [...new Set([...old, ...ids])]
                                : old.filter((id) => !ids.includes(id)),
                            );
                          }}
                        />
                        {name}
                      </label>
                    ) : (
                      name
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.items.map((row) => (
                <tr key={row.id}>
                  {CASE_COLUMNS.map(([key]) => (
                    <td key={key}>
                      {key === 'serial' ? (
                        <label className="case-check">
                          <input
                            type="checkbox"
                            disabled={busy || loading}
                            checked={selected.includes(row.id)}
                            aria-label={`选择用例 ${row.number}`}
                            onChange={(e) =>
                              setSelected((ids) =>
                                e.target.checked
                                  ? [...ids, row.id]
                                  : ids.filter((id) => id !== row.id),
                              )
                            }
                          />
                          {row.serial}
                        </label>
                      ) : key === 'number' ? (
                        <>
                          <button
                            className="case-number"
                            disabled={loading}
                            onClick={() => {
                              setCaseId(row.id);
                              setModal('case');
                            }}
                          >
                            {row.number}
                          </button>
                          <div className="hint">
                            {categoryName(row.category_id)}
                            {row.lifecycle === 'RETIRED' ? ' · 停用' : ''}
                          </div>
                          <div className="row case-row-actions">
                            <button
                              className="ghost small"
                              disabled={busy || loading}
                              aria-label={`编辑用例 ${row.number}`}
                              title="编辑用例"
                              onClick={() => {
                                setCaseId(row.id);
                                setModal('case');
                              }}
                            >
                              <Icon name="edit" />
                            </button>
                            <button
                              className="ghost small danger"
                              disabled={busy || loading}
                              aria-label={`删除用例 ${row.number}`}
                              title="删除用例"
                              onClick={() => {
                                setDeleting(row);
                                setModalError('');
                                setModal('delete-case');
                              }}
                            >
                              <Icon name="trash" />
                            </button>
                          </div>
                        </>
                      ) : key === 'priority' ? (
                        <span className={row.priority === 'P0' ? 'case-priority-high' : ''}>
                          {row.priority}
                        </span>
                      ) : key === 'result' ? (
                        <>
                          <span
                            className={
                              row.result === '通过'
                                ? 'case-result-pass'
                                : row.result === '失败'
                                  ? 'case-result-fail'
                                  : ''
                            }
                          >
                            {row.result}
                          </span>
                          <div className="hint">
                            {row.result_origin === 'IMPORT'
                              ? '导入记录'
                              : row.result_origin === 'MANUAL'
                                ? '人工记录'
                                : ''}
                          </div>
                        </>
                      ) : (
                        <div className="case-cell">{row[key]}</div>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
              {!data?.items.length && (
                <tr>
                  <td colSpan={14}>
                    <div className="empty">
                      {loading ? '正在加载用例…' : '暂无匹配用例，可新建或导入。'}
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="case-pagination">
          <span>
            共 {data?.total ?? 0} 条 · 第 {data?.page ?? 1} / {pages} 页
          </span>
          <div className="row">
            <label className="case-inline-label">
              每页
              <Select
                value={search.page_size}
                onChange={(e) =>
                  setSearch((q) => ({
                    ...q,
                    page: 1,
                    page_size: Number(e) as CaseSearch['page_size'],
                  }))
                }
              >
                {[10, 20, 50, 100].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </Select>
              条
            </label>
            <button
              className="small"
              disabled={loading || (data?.page ?? 1) <= 1}
              onClick={() => setSearch((q) => ({ ...q, page: (data?.page || 1) - 1 }))}
            >
              上一页
            </button>
            <button
              className="small"
              disabled={loading || (data?.page ?? 1) >= pages}
              onClick={() => setSearch((q) => ({ ...q, page: (data?.page || 1) + 1 }))}
            >
              下一页
            </button>
            <PageJump
              page={data?.page ?? 1}
              pages={pages}
              disabled={loading}
              onChange={(page) => setSearch((q) => ({ ...q, page }))}
            />
          </div>
        </div>
      </section>
      <p className="hint">用例编号可重复；导出包含当前筛选的全部用例。</p>
      {modal === 'case' && data && (
        <CaseEditor
          key={caseId ?? 'new'}
          base={base}
          id={caseId}
          metadata={data}
          categoryId={search.category_id || null}
          onSessionEnd={onSessionEnd}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            reload('用例已保存。');
          }}
        />
      )}
      {modal === 'import' && data && (
        <CaseImportDialog
          base={base}
          metadata={data}
          categoryId={search.category_id || null}
          onSessionEnd={onSessionEnd}
          onClose={() => setModal(null)}
          onSaved={(count) => {
            setModal(null);
            setSelected([]);
            reload(`已导入${count}条用例，已保留原文件编号；缺少编号时由平台分配。`);
          }}
        />
      )}
      {modal === 'batch' && (
        <CaseDialog title="批量编辑用例" busy={busy} onClose={() => setModal(null)}>
          <p className="doc-note">逐行编辑或统一修改所选字段。</p>
          <label className="form-field">
            编辑范围
            <Select
              disabled={busy}
              value={editScope}
              onChange={(e) =>
                setEditScope(
                  e === 'selected' ? 'selected' : e === 'project' ? 'project' : 'filtered',
                )
              }
            >
              <option value="selected" disabled={!selected.length}>
                已勾选用例（{selected.length}条，包含其他分页）
              </option>
              <option value="filtered">当前筛选结果（包含其他分页）</option>
              <option value="project">整个项目所有用例（忽略筛选，包含其他分页）</option>
            </Select>
          </label>
          {modalError && (
            <p role="alert" className="form-error">
              {modalError}
            </p>
          )}
          <div className="row">
            <button disabled={busy} onClick={() => setModal(null)}>
              取消
            </button>
            <button className="primary" disabled={busy} onClick={() => void startBatch()}>
              {busy ? '正在加载全部用例…' : '进入批量编辑'}
            </button>
          </div>
        </CaseDialog>
      )}
      {modal === 'delete-case' && deleting && (
        <CaseDialog title="确认删除用例" busy={busy} onClose={() => setModal(null)}>
          <p>
            确定删除用例 {deleting.number}「{deleting.title || '未填写标题'}」吗？
          </p>
          <p className="hint">
            删除后不再显示在列表、导出和重复检查中。内部编号不复用，设计版本、测试记录及导入来源保留；本期不提供恢复入口。
          </p>
          {modalError && (
            <p role="alert" className="form-error">
              {modalError}
            </p>
          )}
          <div className="row">
            <button disabled={busy} onClick={() => setModal(null)}>
              取消
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={() => void mutate(`${deleting.id}/delete`, { confirmed: true })}
            >
              {busy ? '正在删除…' : '确认删除'}
            </button>
          </div>
        </CaseDialog>
      )}
      {modal && ['manage', 'category', 'delete', 'assign'].includes(modal) && data && (
        <CaseDialog
          title={
            modal === 'manage'
              ? '管理用例分类'
              : modal === 'category'
                ? category
                  ? '编辑分类名称'
                  : '创建用例分类'
                : modal === 'assign'
                  ? '批量修改用例分类'
                  : category?.count
                    ? '迁移用例并删除分类'
                    : '确认删除分类'
          }
          busy={busy}
          onClose={() => setModal(null)}
        >
          {modal === 'manage' && (
            <>
              <p className="hint">有关联用例的分类需迁移后删除。</p>
              {data.categories.map((c) => (
                <div className="case-category-row" key={c.id}>
                  <span>
                    {c.name} <small>{c.count} 条用例</small>
                  </span>
                  <div className="row">
                    <button
                      className="ghost small"
                      aria-label={`编辑分类：${c.name}`}
                      onClick={() => openCategory(c)}
                    >
                      <Icon name="edit" />
                    </button>
                    <button
                      className="ghost small danger"
                      aria-label={`删除分类：${c.name}`}
                      onClick={() => {
                        setCategory(c);
                        setTarget(null);
                        setModalError('');
                        setModal('delete');
                      }}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                </div>
              ))}
              {!data.categories.length && <p className="muted">尚未创建分类。</p>}
              <button className="primary" onClick={() => openCategory(null)}>
                创建分类
              </button>
            </>
          )}
          {modal === 'category' && (
            <Form
              onSubmit={(e) => {
                e.preventDefault();
                void mutate(
                  category ? `categories/${category.id}` : 'categories',
                  { name: name.trim() },
                  category ? 'PATCH' : 'POST',
                );
              }}
            >
              <label className="form-field">
                分类名称
                <input
                  required
                  maxLength={80}
                  value={name}
                  disabled={busy}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例如：用户端、Web端"
                />
              </label>
              <p className="hint">同项目名称不能重复；未分类为保留项。</p>
              <button className="primary" disabled={busy || !name.trim()}>
                保存分类
              </button>
            </Form>
          )}
          {modal === 'assign' && (
            <>
              <p>已选{selected.length}条用例，包含其他分页选中的用例。</p>
              <label className="form-field">
                目标分类
                <Select
                  value={target ?? ''}
                  disabled={busy}
                  onChange={(e) => setTarget(e ? Number(e) : null)}
                >
                  <option value="">未分类</option>
                  {data.categories.map((c) => (
                    <option value={c.id} key={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </label>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  void mutate('assign-category', { case_ids: selected, category_id: target })
                }
              >
                保存分类
              </button>
            </>
          )}
          {modal === 'delete' && category && (
            <>
              <p className="doc-note">
                {category.count
                  ? `“${category.name}”关联了${category.count}条用例，请选择其他分类，确认迁移后删除。`
                  : `确定删除空分类“${category.name}”吗？`}
              </p>
              {category.count > 0 &&
                (data.categories.length > 1 ? (
                  <label className="form-field">
                    迁移到其他分类
                    <Select
                      value={target ?? ''}
                      disabled={busy}
                      onChange={(e) => setTarget(e ? Number(e) : null)}
                    >
                      <option value="">请选择目标分类</option>
                      {data.categories
                        .filter((c) => c.id !== category.id)
                        .map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                    </Select>
                  </label>
                ) : (
                  <p>没有其他分类，请先取消并创建目标分类。</p>
                ))}
              <p className="hint">用例本身不会删除，编号、内容和历史记录保留。</p>
              <div className="row">
                <button disabled={busy} onClick={() => setModal('manage')}>
                  取消
                </button>
                <button
                  className="danger"
                  disabled={busy || (category.count > 0 && !target)}
                  onClick={() =>
                    void mutate(`categories/${category.id}/delete`, {
                      target_id: target,
                      confirmed: true,
                    })
                  }
                >
                  {category.count ? '迁移并删除分类' : '确认删除'}
                </button>
              </div>
            </>
          )}
          {modalError && (
            <p role="alert" className="form-error">
              {modalError}
              <button
                disabled={busy}
                onClick={() => {
                  setModal(null);
                  reload();
                }}
              >
                关闭并刷新
              </button>
            </p>
          )}
        </CaseDialog>
      )}
    </section>
  );
}
