import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { FormSelect } from './FormSelect';
import { prototypeError } from './prototypeApi';
export const gitVersionKinds = { branches: '分支', tags: 'Tag', commits: '提交历史' } as const;
export type GitVersionKind = keyof typeof gitVersionKinds;
type Version = { name: string; sha: string; message: string; date: string };
export function parseGitVersions(
  value: unknown,
  projectId: number,
  repositoryId: number,
  kind: GitVersionKind,
  page: number,
  ref: string,
) {
  if (!value || typeof value !== 'object') throw Error('github_versions_invalid');
  const v = value as Record<string, unknown>;
  if (
    v.project_id !== projectId ||
    v.association_id !== repositoryId ||
    v.kind !== kind ||
    v.page !== page ||
    v.ref !== ref ||
    typeof v.has_more !== 'boolean' ||
    !Array.isArray(v.items) ||
    v.items.length > 50
  )
    throw Error('github_versions_invalid');
  const items: Version[] = v.items.map((row: unknown) => {
    if (!row || typeof row !== 'object') throw Error('github_versions_invalid');
    const r = row as Record<string, unknown>;
    if (
      typeof r.name !== 'string' ||
      !r.name ||
      typeof r.sha !== 'string' ||
      !/^[a-f0-9]{40}$/.test(r.sha) ||
      typeof r.message !== 'string' ||
      typeof r.date !== 'string' ||
      (r.date && Number.isNaN(Date.parse(r.date)))
    )
      throw Error('github_versions_invalid');
    return { name: r.name, sha: r.sha, message: r.message, date: r.date };
  });
  return { items, has_more: v.has_more };
}
export function GitVersionPicker({
  label,
  projectId,
  repositoryId,
  connectionId,
  defaultBranch,
  value,
  onChange,
  onSessionEnd,
  disabled = false,
}: {
  label: string;
  projectId: number;
  repositoryId: number;
  connectionId: number;
  defaultBranch: string;
  value: string;
  onChange: (sha: string) => void;
  onSessionEnd: () => void;
  disabled?: boolean;
}) {
  const [kind, setKind] = useState<GitVersionKind>('commits'),
    [branch, setBranch] = useState(defaultBranch),
    [branches, setBranches] = useState<Version[]>([]),
    [branchPage, setBranchPage] = useState(0),
    [branchMore, setBranchMore] = useState(false),
    [items, setItems] = useState<Version[]>([]),
    [page, setPage] = useState(0),
    [more, setMore] = useState(false),
    [search, setSearch] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const controller = useRef(new AbortController()),
    generation = useRef(0);
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    return () => c.abort();
  }, []);
  function clear() {
    generation.current++;
    setItems([]);
    setPage(0);
    setMore(false);
    setError('');
    setSearch('');
    onChange('');
  }
  async function fetchPage(nextKind: GitVersionKind, nextPage: number, ref: string) {
    const query = new URLSearchParams({
      connection_id: String(connectionId),
      kind: nextKind,
      page: String(nextPage),
      ref,
    });
    return parseGitVersions(
      await apiRequest<unknown>(
        `/api/projects/${projectId}/repositories/${repositoryId}/versions?${query}`,
        { signal: controller.current.signal },
      ),
      projectId,
      repositoryId,
      nextKind,
      nextPage,
      ref,
    );
  }
  async function load(append = false, refsOnly = false) {
    if (busy || disabled || !connectionId) return;
    const g = ++generation.current;
    setBusy(true);
    setError('');
    try {
      if (refsOnly) {
        const next = await fetchPage('branches', branchPage + 1, '');
        if (controller.current.signal.aborted || g !== generation.current) return;
        setBranches((old) => [...old, ...next.items]);
        setBranchPage((p) => p + 1);
        setBranchMore(next.has_more);
      } else {
        const nextPage = append ? page + 1 : 1,
          ref = kind === 'commits' ? branch : '';
        const next = await fetchPage(kind, nextPage, ref);
        if (controller.current.signal.aborted || g !== generation.current) return;
        setItems((old) => (append ? [...old, ...next.items] : next.items));
        setPage(nextPage);
        setMore(next.has_more);
        if (!append && value && !next.items.some((x) => x.sha === value)) {
          onChange('');
        }
      }
    } catch (e) {
      if (!controller.current.signal.aborted && g === generation.current)
        setError(
          e instanceof Error && e.message === 'github_versions_invalid'
            ? '版本列表与当前项目、仓库或查询不匹配，请重新读取。'
            : prototypeError(e, onSessionEnd),
        );
    } finally {
      if (!controller.current.signal.aborted) setBusy(false);
    }
  }
  const selected = items.find((x) => x.sha === value),
    visible = items.filter((x) =>
      (x.name + ' ' + x.message + ' ' + x.sha).toLowerCase().includes(search.toLowerCase()),
    );
  return (
    <section className="git-version-picker">
      <h3>{label}</h3>
      <div className="row mt">
        {(Object.entries(gitVersionKinds) as [GitVersionKind, string][]).map(([key, name]) => (
          <button
            type="button"
            className={key === kind ? 'small primary' : 'small ghost'}
            aria-pressed={key === kind}
            disabled={disabled || busy}
            key={key}
            onClick={() => {
              setKind(key);
              clear();
            }}
          >
            {name}
          </button>
        ))}
      </div>
      {kind === 'commits' && (
        <div className="git-history-branch">
          <FormSelect
            label={`${label}历史分支`}
            value={branch}
            options={[
              ...new Map(
                [{ name: defaultBranch, sha: '' }, ...branches]
                  .filter((x) => x.name)
                  .map((x) => [x.name, { value: x.name, label: x.name }]),
              ).values(),
            ]}
            disabled={disabled || busy}
            onChange={(v) => {
              setBranch(v);
              clear();
            }}
          />
          <button
            type="button"
            className="small"
            disabled={
              disabled ||
              busy ||
              !connectionId ||
              (branchPage > 0 && !branchMore) ||
              branchPage >= 1000
            }
            onClick={() => void load(false, true)}
          >
            {branchPage ? '更多分支' : '读取分支'}
          </button>
        </div>
      )}
      <div className="row mt">
        <button
          type="button"
          className="small"
          disabled={disabled || busy || !connectionId || (kind === 'commits' && !branch)}
          onClick={() => void load()}
        >
          {busy ? '读取中…' : page ? '刷新版本列表' : '读取版本列表'}
        </button>
        {more && (
          <button
            type="button"
            className="small"
            disabled={disabled || busy || page >= 1000}
            onClick={() => void load(true)}
          >
            加载更多
          </button>
        )}
        <span className="hint">已加载{items.length}项</span>
      </div>
      {page > 0 && (
        <>
          <label className="form-field mt">
            搜索已加载版本
            <input
              type="search"
              value={search}
              disabled={disabled || busy}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="提交说明、分支、Tag或SHA"
            />
          </label>
          <div className="git-version-list" role="group" aria-label={`${label}版本列表`}>
            {visible.map((x, i) => (
              <button
                type="button"
                key={`${x.name}:${x.sha}:${i}`}
                className={`git-version-option ${value === x.sha ? 'selected' : ''}`}
                aria-pressed={value === x.sha}
                disabled={disabled || busy}
                onClick={() => onChange(x.sha)}
              >
                <strong>{kind === 'commits' ? x.message || '无提交说明' : x.name}</strong>
                <small>
                  {x.date ? `${new Date(x.date).toLocaleString()} · ` : ''}
                  {x.sha.slice(0, 12)}
                </small>
              </button>
            ))}
            {!visible.length && (
              <p className="hint">
                {items.length
                  ? '已加载版本中没有匹配项，可继续加载或调整搜索。'
                  : '该范围暂无版本记录。'}
              </p>
            )}
          </div>
        </>
      )}
      {value && (
        <p className="hint mono mt">
          已选{selected ? ` ${selected.name}` : ''}：{value}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {page >= 1000 && more && <p className="hint">已达到读取页数上限，请缩小提交历史分支范围。</p>}
    </section>
  );
}
