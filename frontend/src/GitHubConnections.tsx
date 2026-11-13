import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { Select } from './FormSelect';
import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { apiRequest, encryptedRequest } from './api/http';
import { requestError, groupRepositories, parseProbeResult } from './githubApi';
import type { GitHubConnection, GitHubRepository } from './githubApi';

export function GitHubConnections({ onSessionEnd }: { onSessionEnd: () => void }) {
  const [connections, setConnections] = useState<GitHubConnection[]>([]);
  const [editing, setEditing] = useState<GitHubConnection | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savedNotice, setSavedNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<GitHubConnection | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    apiRequest<GitHubConnection[]>('/api/github/connections', { signal: controller.signal })
      .then(setConnections)
      .catch((e) => {
        if (!controller.signal.aborted) setError(requestError(e, onSessionEnd));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision, onSessionEnd]);

  return (
    <section className="panel panel-pad">
      <div className="row between">
        <h2>GitHub 连接配置</h2>
        <button
          className="primary"
          disabled={busy || loading}
          onClick={() => {
            setEditing(null);
            setSavedNotice('');
            setRevision((v) => v + 1);
            setError('');
          }}
        >
          新增连接
        </button>
      </div>
      <p className="hint mt">
        每个账号独立管理自己的连接，不共享凭据。填写 Token
        后自动发现可访问仓库，按所属个人或组织分组。仅支持 GitHub.com。
      </p>
      <section className="gh-section mt" aria-labelledby="github-my-connections">
        <div className="gh-section-head">
          <div>
            <h3 id="github-my-connections">我的连接</h3>
            <p>选择一项连接，在下方查看或修改配置。</p>
          </div>
          <span className="badge green">{connections.length} 个连接</span>
        </div>
        <div className="gh-connection-list">
          {loading ? (
            <p role="status">正在加载…</p>
          ) : connections.length ? (
            connections.map((c) => (
              <div
                className={`gh-connection-card${editing?.id === c.id ? ' active' : ''}`}
                key={c.id}
              >
                <span className="gh-card-icon" aria-hidden="true">
                  <Icon name="github" />
                </span>
                <div>
                  <div className="row">
                    <strong>{c.name}</strong>
                    {editing?.id === c.id && <span className="badge green">正在编辑</span>}
                  </div>
                  <p className="hint">
                    {c.token_type === 'classic' ? 'Classic Token' : 'Fine-grained Token'} ·{' '}
                    {c.github_login} · 已选 {c.repositories.length} 个仓库
                  </p>
                </div>
                <div className="row" style={{ flex: 'none' }}>
                  <button
                    disabled={busy}
                    onClick={() => {
                      setEditing(c);
                      setSavedNotice('');
                      setError('');
                    }}
                  >
                    修改
                  </button>
                  <button
                    className="danger"
                    disabled={busy}
                    onClick={() => {
                      setError('');
                      setDeleting(c);
                    }}
                  >
                    <Icon name="trash" />
                    删除
                  </button>
                </div>
              </div>
            ))
          ) : (
            <p className="muted mt">暂无连接。可分别添加个人和已加入组织的连接。</p>
          )}
        </div>
      </section>
      <div className="divider" />
      {!loading && (
        <ConnectionEditor
          key={`${editing?.id || 'new'}-${revision}`}
          connection={editing}
          busy={busy}
          setBusy={setBusy}
          onSessionEnd={onSessionEnd}
          onSaved={(c) => {
            setConnections((items) =>
              [...items.filter((item) => item.id !== c.id), c].sort((a, b) => a.id - b.id),
            );
            setEditing(c);
            setSavedNotice('✓ 连接配置已保存，所选仓库已通过分支读取检查。');
          }}
        />
      )}
      {error && (
        <p className="form-error mt" role="alert">
          {error}
        </p>
      )}
      {deleting && (
        <CaseDialog title="删除 GitHub 连接" busy={busy} onClose={() => setDeleting(null)}>
          <p>
            确认删除连接“{deleting.name}”？将移除本平台保存的凭据和 {deleting.repositories.length}{' '}
            个仓库授权，不删除 GitHub 仓库，也不撤销 GitHub 上的 Token。
          </p>
          <p className="hint mt">项目仓库关联和历史资料保留；后续读取需其他有效的个人连接。</p>
          {error && (
            <p className="form-error mt" role="alert">
              {error}
            </p>
          )}
          <div className="row mt">
            <button disabled={busy} onClick={() => setDeleting(null)}>
              取消
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError('');
                try {
                  await apiRequest(`/api/github/connections/${deleting.id}`, {
                    method: 'DELETE',
                    body: JSON.stringify({ version: deleting.version, confirmed: true }),
                  });
                  setConnections((items) => items.filter((item) => item.id !== deleting.id));
                  if (editing?.id === deleting.id) setEditing(null);
                  setDeleting(null);
                  setSavedNotice('✓ GitHub 连接已删除，远端仓库未修改。');
                } catch (e) {
                  setError(requestError(e, onSessionEnd));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? '正在删除…' : '确认删除连接'}
            </button>
          </div>
        </CaseDialog>
      )}
      {savedNotice && (
        <p className="account-notice mt" role="status">
          {savedNotice}
        </p>
      )}
      <button
        className="small mt"
        disabled={busy || loading}
        onClick={() => {
          setEditing(null);
          setError('');
          setRevision((v) => v + 1);
        }}
      >
        重新加载连接
      </button>
    </section>
  );
}

function ConnectionEditor({
  connection,
  busy,
  setBusy,
  onSessionEnd,
  onSaved,
}: {
  connection: GitHubConnection | null;
  busy: boolean;
  setBusy: (value: boolean) => void;
  onSessionEnd: () => void;
  onSaved: (connection: GitHubConnection) => void;
}) {
  const [name, setName] = useState(connection?.name || '');
  const [tokenType, setTokenType] = useState<'classic' | 'fine_grained'>(
    connection?.token_type || 'classic',
  );
  const [savedTokenType, setSavedTokenType] = useState(connection?.token_type);
  const [token, setToken] = useState('');
  const [version, setVersion] = useState(connection?.version || 0);
  const [repos, setRepos] = useState<GitHubRepository[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [receipts, setReceipts] = useState<string[]>([]);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [id, setId] = useState(connection?.id || null);
  const [hasToken, setHasToken] = useState(connection?.has_token || false);

  function invalidate() {
    setRepos([]);
    setSelected([]);
    setReceipts([]);
    setPage(0);
    setHasMore(false);
    setNotice('');
    setError('');
  }
  function payload() {
    return {
      connection_id: id,
      version,
      name,
      token_type: tokenType,
      token,
      api_url: 'https://api.github.com',
    };
  }
  async function probe(nextPage: number) {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    if (nextPage === 1) invalidate();
    try {
      const result = parseProbeResult(
        await encryptedRequest<unknown>('/api/github/connections/probe', {
          ...payload(),
          page: nextPage,
        }),
      );
      setRepos((items) => [
        ...new Map(
          [...(nextPage === 1 ? [] : items), ...result.repositories].map((r) => [r.github_id, r]),
        ).values(),
      ]);
      setReceipts((items) => (nextPage === 1 ? [result.receipt] : [...items, result.receipt]));
      setPage(result.page);
      setHasMore(result.has_more);
      setNotice(
        result.repositories.length
          ? `✓ 身份 ${result.github_login} 已验证，本页找到 ${result.repositories.length} 个仓库。请勾选；保存时将验证分支读取权限。`
          : `身份 ${result.github_login} 已验证，本页没有可访问仓库。${result.has_more ? '请继续加载下一页。' : '请核对仓库授权、组织策略及SSO，尚未确认连接可用。'}`,
      );
    } catch (e) {
      setError(requestError(e, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await encryptedRequest<GitHubConnection>('/api/github/connections', {
        ...payload(),
        repository_ids: selected,
        receipts,
      });
      setVersion(result.version);
      setId(result.id);
      setHasToken(true);
      setSavedTokenType(result.token_type);
      setToken('');
      setReceipts([]);
      setRepos([]);
      setSelected([]);
      setHasMore(false);
      setPage(0);
      onSaved(result);
      setNotice('✓ 配置已保存，所选仓库已通过分支读取检查。凭据不会回显。');
    } catch (e) {
      setError(requestError(e, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Form
      onSubmit={(e) => {
        e.preventDefault();
        const button = (e.nativeEvent as SubmitEvent).submitter;
        void (button instanceof HTMLButtonElement && button.value === 'save' ? save() : probe(1));
      }}
    >
      <h3>{id ? '修改连接' : '新增连接'}</h3>
      <div className="ai-form-grid mt">
        <label className="form-field ai-full">
          连接名称
          <input
            value={name}
            required
            maxLength={80}
            disabled={busy}
            onChange={(e) => {
              setName(e.target.value);
              setNotice('');
            }}
          />
        </label>
        <label className="form-field">
          访问方式
          <Select
            value={tokenType}
            disabled={busy}
            onChange={(e) => {
              setTokenType(e as 'classic' | 'fine_grained');
              setToken('');
              invalidate();
            }}
          >
            <option value="classic">Classic Token</option>
            <option value="fine_grained">Fine-grained Token</option>
            <option value="github_app" disabled>
              GitHub App（待支持）
            </option>
          </Select>
        </label>
        <label className="form-field">
          API 地址
          <input value="https://api.github.com" readOnly />
        </label>
        <label className="form-field ai-full">
          访问凭据
          <input
            required={!hasToken || savedTokenType !== tokenType}
            type="password"
            autoComplete="new-password"
            value={token}
            maxLength={512}
            disabled={busy}
            placeholder={
              hasToken && savedTokenType === tokenType
                ? '已配置；留空保留，填写替换'
                : tokenType === 'classic'
                  ? 'ghp_…'
                  : 'github_pat_…'
            }
            onChange={(e) => {
              setToken(e.target.value);
              invalidate();
            }}
          />
        </label>
      </div>
      <p className="hint mt">
        {tokenType === 'classic'
          ? 'Classic 可发现该 Token 有权访问的个人、组织和协作仓库。私有仓库通常需 repo 权限（本身含写入能力），平台仍只执行读取操作。'
          : 'Fine-grained 只会发现这枚 Token 已获授权的仓库，使用 Contents Read 和 Metadata Read；组织可能要求审批。'}
        无需填写连接类型或组织名称；测试后按所属个人/组织分组选择。切换访问方式需要重新填写匹配的
        Token。
      </p>
      <div className="row mt">
        <button type="submit" value="test" disabled={busy}>
          测试连接
        </button>
        {busy && <span role="status">正在读取和校验，请稍候…</span>}
      </div>
      {notice && (
        <p className="account-notice mt" role="status">
          {notice}
        </p>
      )}
      <div className="divider" />
      <section className="gh-section" aria-labelledby="github-allowed-repositories">
        <div className="gh-section-head">
          <div>
            <h3 id="github-allowed-repositories">允许读取的仓库</h3>
            <p>勾选后才会加入本连接的读取范围。</p>
          </div>
          <span className="badge green">已选 {selected.length} / 20</span>
        </div>
        <div className="gh-repository-body">
          {connection?.repositories.length ? (
            <p className="hint mt">
              上次保存：{connection.repositories.map((r) => r.full_name).join('、')}
              。重新测试后请重新勾选需要保留的仓库。
            </p>
          ) : null}
          <label className="form-field mt">
            搜索已加载仓库
            <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          {groupRepositories(
            repos.filter((r) => r.full_name.toLowerCase().includes(search.toLowerCase())),
          ).map(([owner, items]) => (
            <div className="gh-owner-group" key={owner}>
              <h4 className="gh-owner-title">
                {owner}
                <span className="badge">{items.length} 个仓库</span>
              </h4>
              {items.map((r) => (
                <label className="gh-repo-card" key={r.github_id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(r.github_id)}
                    disabled={busy || (!selected.includes(r.github_id) && selected.length >= 20)}
                    onChange={(e) =>
                      setSelected((ids) =>
                        e.target.checked
                          ? [...ids, r.github_id]
                          : ids.filter((v) => v !== r.github_id),
                      )
                    }
                  />
                  <span>
                    <strong>{r.full_name}</strong>
                    <br />
                    <span className="hint">
                      {r.private ? '私有' : '公开'} · 默认分支 {r.default_branch || '未初始化'}
                    </span>
                  </span>
                  <span className="gh-selection-label">
                    {selected.includes(r.github_id) ? '已选择' : '选择'}
                  </span>
                </label>
              ))}
            </div>
          ))}
          {!repos.length && <p className="hint mt">尚无可供选择的仓库。请先测试连接。</p>}
          {hasMore && (
            <button
              type="button"
              className="mt"
              disabled={busy || receipts.length >= 20}
              onClick={() => void probe(page + 1)}
            >
              加载下一页
            </button>
          )}
          {receipts.length >= 20 && hasMore && (
            <p className="hint">本次已加载20页；请在 GitHub 缩小 Token 的仓库授权范围后重试。</p>
          )}
        </div>
      </section>
      <p className="hint mt">
        仅勾选的仓库允许后续读取。保存前重新验证所选仓库，最多等待约3分钟；不拉取代码、不建立快照、不调用
        AI，不执行任何 GitHub 写入。
      </p>
      <button
        type="submit"
        value="save"
        className="primary mt"
        disabled={busy || !selected.length || !receipts.length}
      >
        保存配置
      </button>
      {error && (
        <p className="form-error mt" role="alert">
          {error}
        </p>
      )}
    </Form>
  );
}
