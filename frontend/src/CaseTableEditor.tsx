import { PageJump } from './PageJump';
import { Select } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import { useBlocker } from 'react-router-dom';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import {
  CASE_COLUMNS,
  CASE_RESULTS,
  PRIORITIES,
  DESIGN_FIELDS,
  caseChanges,
  caseError,
  parseBatchResult,
} from './caseApi';
import type { CaseChanges, CaseList, CaseRow, CaseEditScope, EditableField } from './caseApi';

function Field({
  field,
  value,
  label,
  disabled,
  onChange,
}: {
  field: EditableField;
  value: string;
  label: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const options = field === 'priority' ? PRIORITIES : field === 'result' ? CASE_RESULTS : null;
  return options ? (
    <Select aria-label={label} disabled={disabled} value={value} onChange={(e) => onChange(e)}>
      {options.map((v) => (
        <option key={v} value={v}>
          {v || '留空'}
        </option>
      ))}
    </Select>
  ) : (
    <textarea
      aria-label={label}
      disabled={disabled}
      value={value}
      rows={3}
      maxLength={
        field === 'tester' || field === 'case_type'
          ? 200
          : field === 'module'
            ? 500
            : field === 'structure'
              ? 1000
              : field === 'remark'
                ? 10000
                : ['steps', 'expected', 'preconditions'].includes(field)
                  ? 30000
                  : 4000
      }
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function CaseTableEditor({
  base,
  snapshot,
  search,
  singleId,
  scopeLabel,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  base: string;
  snapshot: CaseList;
  search: CaseEditScope;
  singleId: number | null;
  scopeLabel: string;
  onClose: () => void;
  onSaved: (message: string) => void;
  onSessionEnd: () => void;
}) {
  const [drafts, setDrafts] = useState<Record<number, CaseRow>>({});
  const [page, setPage] = useState(1),
    [size, setSize] = useState(10);
  const [uniform, setUniform] = useState(false),
    [values, setValues] = useState<CaseChanges>({});
  const [confirm, setConfirm] = useState<'rows' | 'uniform' | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [leave, setLeave] = useState<(() => void) | null>(null);
  const root = useRef<HTMLElement>(null),
    pending = useRef(false),
    bypass = useRef(false),
    alive = useRef(true);
  const patches = snapshot.items.flatMap((row) => {
    const changes = drafts[row.id] ? caseChanges(row, drafts[row.id]) : {};
    return Object.keys(changes).length ? [{ id: row.id, changes }] : [];
  });
  const dirty = patches.length > 0 || Object.keys(values).length > 0;
  const blocker = useBlocker(() => (dirty || pending.current) && !bypass.current);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => {
      if (dirty || pending.current) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    const click = (event: MouseEvent) => {
      const target =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>('a,button,summary')
          : null;
      if (
        !target ||
        root.current?.contains(target) ||
        bypass.current ||
        (!dirty && !pending.current)
      )
        return;
      event.preventDefault();
      event.stopPropagation();
      if (!pending.current)
        setLeave(() => () => {
          bypass.current = true;
          onClose();
          target.click();
        });
    };
    window.addEventListener('beforeunload', unload);
    document.addEventListener('click', click, true);
    return () => {
      window.removeEventListener('beforeunload', unload);
      document.removeEventListener('click', click, true);
    };
  }, [dirty, onClose]);
  function close() {
    if (dirty) setLeave(() => onClose);
    else onClose();
  }
  async function save(mode: 'rows' | 'uniform') {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const result = parseBatchResult(
        await apiRequest<unknown>(`${base}/batch-edit`, {
          method: 'POST',
          timeoutMs: 180000,
          body: JSON.stringify({
            revision: snapshot.revision,
            confirmed: true,
            search,
            mode,
            ...(mode === 'rows' ? { rows: patches } : { changes: values }),
          }),
        }),
      );
      if (alive.current) onSaved(`已保存${result.updated}条用例。`);
    } catch (e) {
      if (alive.current) {
        setError(caseError(e, onSessionEnd));
        setConfirm(null);
      }
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const affected = confirm === 'uniform' ? snapshot.items.length : patches.length;
  const designChanged =
    confirm === 'uniform'
      ? Object.keys(values).some((f) => DESIGN_FIELDS.some((d) => d === f))
      : patches.some((p) => Object.keys(p.changes).some((f) => DESIGN_FIELDS.some((d) => d === f)));
  return (
    <section className="cases-page case-inline-editor" ref={root}>
      <header className="page-head">
        <div>
          <h1>用例管理</h1>
          <p>
            {singleId ? '行内编辑' : '批量编辑'} · {scopeLabel} · 共{snapshot.items.length}条
          </p>
        </div>
        <div className="row">
          {!singleId && (
            <button disabled={busy || patches.length > 0} onClick={() => setUniform(true)}>
              统一修改字段
            </button>
          )}
          <button disabled={busy} onClick={close}>
            取消编辑
          </button>
          <button
            className="primary"
            disabled={busy || !patches.length}
            onClick={() => setConfirm('rows')}
          >
            保存{patches.length ? ` ${patches.length} 条修改` : '修改'}
          </button>
        </div>
      </header>
      <p className="doc-note">跨页修改会保留，点击保存后统一提交。</p>
      {error && (
        <p role="alert" className="form-error">
          {error} 草稿仍保留；若版本冲突，请先复制需要的内容，退出编辑并刷新后重试。
        </p>
      )}
      <div className="panel">
        <div className="case-table-scroll" tabIndex={0} aria-label="编辑用例列表">
          <table className="case-table">
            <thead>
              <tr>
                {CASE_COLUMNS.map(([key, label]) => (
                  <th key={key}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {snapshot.items.slice((page - 1) * size, page * size).map((original) => {
                const row = drafts[original.id] || original;
                const editable = singleId === null || singleId === row.id;
                return (
                  <tr key={row.id}>
                    {CASE_COLUMNS.map(([key, label]) => (
                      <td key={key}>
                        {key === 'serial' || key === 'number' || !editable ? (
                          <div className="case-cell">{row[key]}</div>
                        ) : (
                          <Field
                            field={key}
                            value={row[key]}
                            label={`用例 ${row.number} ${label}`}
                            disabled={busy}
                            onChange={(value) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [row.id]: { ...(prev[row.id] || original), [key]: value },
                              }))
                            }
                          />
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="case-pagination">
          <span>
            共{snapshot.items.length}条 · 第{page}/
            {Math.max(1, Math.ceil(snapshot.items.length / size))}页 · 已改{patches.length}条
          </span>
          <div className="row">
            <Select
              aria-label="每页条数"
              disabled={busy}
              value={size}
              onChange={(e) => {
                setSize(Number(e));
                setPage(1);
              }}
            >
              {[10, 20, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}条/页
                </option>
              ))}
            </Select>
            <button disabled={busy || page === 1} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            <button
              disabled={busy || page * size >= snapshot.items.length}
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
            <PageJump
              page={page}
              onChange={setPage}
              pages={Math.max(1, Math.ceil(snapshot.items.length / size))}
              disabled={busy}
            />
          </div>
        </div>
      </div>
      {uniform && (
        <CaseDialog title="统一修改字段" busy={busy} onClose={() => setUniform(false)} wide>
          <p className="doc-note">
            范围：{scopeLabel}，共{snapshot.items.length}
            条，包含其他分页。仅修改勾选字段；勾选后留空表示清空该字段。
          </p>
          <div className="case-form-grid">
            {CASE_COLUMNS.map(([key, label]) =>
              key === 'serial' || key === 'number' ? null : (
                <div className="form-field" key={key}>
                  <label className="row">
                    <input
                      type="checkbox"
                      checked={key in values}
                      onChange={(e) =>
                        setValues((old) => {
                          const next = { ...old };
                          if (e.target.checked) next[key] = '';
                          else delete next[key];
                          return next;
                        })
                      }
                    />
                    {label}
                  </label>
                  {key in values && (
                    <Field
                      field={key}
                      value={values[key] || ''}
                      label={`统一修改${label}`}
                      disabled={busy}
                      onChange={(value) => setValues((old) => ({ ...old, [key]: value }))}
                    />
                  )}
                </div>
              ),
            )}
          </div>
          <div className="row">
            <button onClick={() => setUniform(false)}>返回列表</button>
            <button
              className="primary"
              disabled={!Object.keys(values).length}
              onClick={() => {
                setUniform(false);
                setConfirm('uniform');
              }}
            >
              核对并保存
            </button>
          </div>
        </CaseDialog>
      )}
      {confirm && (
        <CaseDialog title="确认保存用例" busy={busy} onClose={() => setConfirm(null)}>
          <p>
            将{confirm === 'uniform' ? '统一修改' : '保存'}
            {affected}条用例。范围：{scopeLabel}。
          </p>
          {confirm === 'uniform' && (
            <ul>
              {CASE_COLUMNS.filter(([key]) => key in values).map(([key, label]) => (
                <li key={key}>
                  {label}：
                  <span className="case-cell">{values[key as EditableField] || '（清空）'}</span>
                </li>
              ))}
            </ul>
          )}
          {designChanged && (
            <p className="form-error">
              修改设计将生成新版本，重置为“未测、待审核”，测试人员清空；本次测试结果不沿用。
            </p>
          )}
          <p className="hint">任一条失败或版本已变化时，整批不保存。</p>
          <div className="row">
            <button disabled={busy} onClick={() => setConfirm(null)}>
              返回编辑
            </button>
            <button className="primary" disabled={busy} onClick={() => void save(confirm)}>
              {busy ? '正在保存…' : '确认保存'}
            </button>
          </div>
        </CaseDialog>
      )}
      {blocker.state === 'blocked' && !leave && (
        <CaseDialog
          title={busy ? '正在保存，请稍候' : '放弃未保存修改？'}
          busy={busy}
          onClose={() => blocker.reset()}
        >
          <p>{busy ? '保存结果返回前请留在当前页面。' : '离开后本次草稿将丢失。'}</p>
          <div className="row">
            <button onClick={() => blocker.reset()}>留在当前页</button>
            <button className="danger" disabled={busy} onClick={() => blocker.proceed()}>
              放弃修改并离开
            </button>
          </div>
        </CaseDialog>
      )}
      {leave && (
        <CaseDialog title="放弃未保存修改？" busy={busy} onClose={() => setLeave(null)}>
          <p>离开后本次草稿将丢失，尚未修改已保存的用例。</p>
          <div className="row">
            <button onClick={() => setLeave(null)}>继续编辑</button>
            <button
              className="danger"
              onClick={() => {
                setLeave(null);
                leave();
              }}
            >
              放弃修改并离开
            </button>
          </div>
        </CaseDialog>
      )}
    </section>
  );
}
