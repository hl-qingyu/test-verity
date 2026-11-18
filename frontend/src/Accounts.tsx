import { PageJump } from './PageJump';
import { Form } from './Form';
import { Select } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { User } from './Auth';
import { postEncrypted } from './passwordTransport';
import { platformRoleLabels } from './accountRoles';

type Account = User & { status: 'ACTIVE' | 'DISABLED'; created_at: string; updated_at: string };
type Action = { kind: 'create' } | { kind: 'edit' | 'delete' | 'reset'; account: Account };
const actionTitles = {
  create: '创建账号',
  edit: '修改账号',
  delete: '删除账号',
  reset: '重置密码',
};
const errorMessages: Record<string, string> = {
  invalid_password_envelope: '安全校验已失效，请重新提交。',
  too_many_attempts: '尝试次数过多，请稍后重试。',
  login_name_unavailable: '账号已被使用（包括已删除账号），请使用其他账号。',
  account_changed: '账号已被其他管理员修改，请关闭窗口、刷新列表后重试。',
  cannot_disable_self: '不能停用自己或移除自己的管理员权限。',
  cannot_delete_self: '不能删除当前登录账号。',
  last_admin_required: '至少需要保留一个可用的平台管理员。',
  user_not_found: '账号已不存在，请刷新列表。',
  admin_required: '仅平台管理员可以管理账号。',
  origin_not_allowed: '当前访问地址未获允许。',
  invalid_request: '请检查字段格式和两次密码是否一致。',
  service_unavailable: '服务暂不可用，请稍后重试。',
};

export function Accounts({
  user,
  onSessionEnd,
  onUserChange,
}: {
  user: User;
  onSessionEnd: () => void;
  onUserChange: (user: User) => void;
}) {
  const [items, setItems] = useState<Account[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [action, setAction] = useState<Action | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    async function load() {
      try {
        const params = new URLSearchParams({ page: String(page), search });
        const response = await fetch(`/api/users?${params}`, {
          cache: 'no-store',
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
        });
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          onSessionEnd();
          return;
        }
        if (!response.ok)
          throw new Error(
            response.status === 403 ? '仅平台管理员可以管理账号。' : '账号列表加载失败，请重试。',
          );
        const result: { items: Account[]; total: number } = await response.json();
        if (!controller.signal.aborted) {
          setItems(result.items);
          setTotal(result.total);
        }
      } catch (failure) {
        if (!controller.signal.aborted)
          setError(failure instanceof Error ? failure.message : '连接失败，请重试。');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [page, search, revision, onSessionEnd]);

  function start(next: Action) {
    setNotice('');
    setAction(next);
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>账号管理</h2>
        <button className="primary" onClick={() => start({ kind: 'create' })}>
          ＋ 创建账号
        </button>
      </div>
      <div className="panel-pad">
        <Form
          className="row mb"
          onSubmit={(event) => {
            event.preventDefault();
            setSearch(String(new FormData(event.currentTarget).get('search') || '').trim());
            setPage(1);
            setRevision((value) => value + 1);
          }}
        >
          <label className="form-field grow">
            <span className="screen-reader">搜索账号或显示名</span>
            <input name="search" maxLength={80} placeholder="搜索账号或显示名" />
          </label>
          <button type="submit">搜索</button>
          <button type="button" onClick={() => setRevision((value) => value + 1)}>
            刷新
          </button>
        </Form>
        {notice && (
          <p role="status" className="account-notice mb">
            {notice}
          </p>
        )}
        {error ? (
          <p role="alert" className="form-error">
            {error}
          </p>
        ) : loading ? (
          <p role="status" className="muted">
            正在加载账号…
          </p>
        ) : (
          <>
            <div className="account-table-wrap">
              <table className="account-table">
                <thead>
                  <tr>
                    <th>账号</th>
                    <th>显示名</th>
                    <th>平台角色</th>
                    <th>状态</th>
                    <th>创建时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((account) => (
                    <tr key={account.id}>
                      <td>
                        {account.login_name}
                        {account.id === user.id && <span className="badge">当前账号</span>}
                      </td>
                      <td>{account.display_name}</td>
                      <td>{platformRoleLabels[account.platform_role]}</td>
                      <td>
                        <span
                          className={`badge ${account.status === 'ACTIVE' ? 'green' : 'orange'}`}
                        >
                          {account.status === 'ACTIVE' ? '启用' : '停用'}
                        </span>
                      </td>
                      <td>{new Date(account.created_at).toLocaleString('zh-CN')}</td>
                      <td>
                        <div className="row account-actions">
                          <button className="link" onClick={() => start({ kind: 'edit', account })}>
                            修改
                          </button>
                          <button
                            className="link"
                            onClick={() => start({ kind: 'reset', account })}
                          >
                            重置密码
                          </button>
                          <button
                            className="link danger"
                            disabled={account.id === user.id}
                            title={account.id === user.id ? '不能删除当前登录账号' : undefined}
                            onClick={() => start({ kind: 'delete', account })}
                          >
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {items.length === 0 && (
              <div className="empty">
                <h3>没有符合条件的账号</h3>
              </div>
            )}
            <div className="between mt smalltext">
              <span className="muted">
                共 {total} 个账号 · 第 {page} 页
              </span>
              <div className="row">
                <button className="small" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  上一页
                </button>
                <button
                  className="small"
                  disabled={page * 20 >= total}
                  onClick={() => setPage(page + 1)}
                >
                  下一页
                </button>
                <PageJump
                  page={page}
                  onChange={setPage}
                  pages={Math.max(1, Math.ceil(total / 20))}
                  disabled={loading}
                />
              </div>
            </div>
          </>
        )}
        <p className="hint mt">业务角色不影响项目权限，项目权限由负责人和成员配置决定。</p>
      </div>
      {action && (
        <AccountDialog
          action={action}
          user={user}
          onClose={() => setAction(null)}
          onSessionEnd={onSessionEnd}
          onSaved={(updated) => {
            if ('account' in action && action.account.id === user.id) {
              if (action.kind === 'reset' || (updated && updated.login_name !== user.login_name)) {
                onSessionEnd();
                return;
              }
              if (updated) onUserChange(updated);
            }
            setNotice(`${actionTitles[action.kind]}成功。`);
            setAction(null);
            if (action.kind === 'delete' && items.length === 1 && page > 1) setPage(page - 1);
            setRevision((value) => value + 1);
          }}
        />
      )}
    </section>
  );
}

function AccountDialog({
  action,
  user,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  action: Action;
  user: User;
  onClose: () => void;
  onSaved: (account?: Account) => void;
  onSessionEnd: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const account = 'account' in action ? action.account : undefined;
  const editsFields = action.kind === 'create' || action.kind === 'edit';
  const editsPassword = action.kind === 'create' || action.kind === 'reset';
  const isSelf = account?.id === user.id;

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    const payload: Record<string, string> = {};
    if (editsFields) {
      for (const name of ['login_name', 'display_name', 'platform_role', 'status'])
        payload[name] = String(data.get(name) || '').trim();
      if (isSelf) {
        payload.platform_role = 'ADMIN';
        payload.status = 'ACTIVE';
      }
      if (account) payload.updated_at = account.updated_at;
    }
    if (editsPassword) {
      payload.password = String(data.get('password') || '');
      payload.confirm_password = String(data.get('confirm_password') || '');
      if (payload.password !== payload.confirm_password) {
        setError('两次密码不一致。');
        return;
      }
      if (!payload.password.trim()) {
        setError('密码不能全为空格。');
        return;
      }
    }
    setBusy(true);
    setError('');
    const url =
      action.kind === 'create'
        ? '/api/users'
        : `/api/users/${account?.id}${action.kind === 'reset' ? '/reset-password' : ''}`;
    const method = { create: 'POST', edit: 'PATCH', reset: 'POST', delete: 'DELETE' }[action.kind];
    try {
      const response = editsPassword
        ? await postEncrypted(url, payload)
        : await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: action.kind === 'delete' ? undefined : JSON.stringify(payload),
            signal: AbortSignal.timeout(15000),
          });
      if (response.status === 401) {
        onSessionEnd();
        return;
      }
      if (!response.ok) {
        const result: { detail?: string } = await response.json();
        setError(errorMessages[result.detail || ''] || '操作未完成，请刷新列表后重试。');
        return;
      }
      onSaved(response.status === 204 ? undefined : await response.json());
    } catch {
      setError('连接中断，结果尚未确认。请关闭窗口、刷新列表核对后再操作。');
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="account-dialog"
      aria-labelledby="account-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <Form onSubmit={submit}>
        <div className="panel-head">
          <h2 id="account-dialog-title">{actionTitles[action.kind]}</h2>
          <button
            className="ghost small"
            type="button"
            aria-label="关闭"
            disabled={busy}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="panel-pad stack">
          {editsFields && (
            <>
              <label className="form-field">
                账号
                <input
                  name="login_name"
                  defaultValue={account?.login_name || ''}
                  required
                  pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{2,63}"
                  minLength={3}
                  maxLength={64}
                  autoCapitalize="none"
                  autoComplete="off"
                  disabled={busy}
                />
                <span className="hint">3–64位字母、数字、点、下划线或连字符；统一保存为小写。</span>
              </label>
              <label className="form-field">
                显示名
                <input
                  name="display_name"
                  defaultValue={account?.display_name || ''}
                  required
                  maxLength={80}
                  disabled={busy}
                />
              </label>
              <div className="account-form-grid">
                <label className="form-field">
                  平台角色
                  <Select
                    name="platform_role"
                    defaultValue={account?.platform_role || 'TEST'}
                    disabled={busy || isSelf}
                  >
                    {account?.platform_role === 'USER' && <option value="USER">普通用户</option>}
                    {Object.entries(platformRoleLabels)
                      .filter(([role]) => role !== 'USER')
                      .map(([role, label]) => (
                        <option key={role} value={role}>
                          {label}
                        </option>
                      ))}
                  </Select>
                </label>
                <label className="form-field">
                  状态
                  <Select
                    name="status"
                    defaultValue={account?.status || 'ACTIVE'}
                    disabled={busy || isSelf}
                  >
                    <option value="ACTIVE">启用</option>
                    <option value="DISABLED">停用</option>
                  </Select>
                </label>
              </div>

              {action.kind === 'edit' && (
                <p className="hint">修改账号、角色或启用状态后，该用户需重新登录。</p>
              )}
            </>
          )}
          {action.kind === 'reset' && (
            <p>
              为 <strong>{account?.login_name}</strong> 设置新密码后，该账号的所有登录会话立即失效。
            </p>
          )}
          {editsPassword && (
            <>
              <label className="form-field">
                {action.kind === 'reset' ? '新密码' : '初始密码'}
                <input
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  required
                  disabled={busy}
                />
                <span className="hint">8–128个字符，不能全为空格。</span>
              </label>
              <label className="form-field">
                确认密码
                <input
                  name="confirm_password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  required
                  disabled={busy}
                />
              </label>
              <label className="row smalltext">
                <input
                  type="checkbox"
                  checked={showPassword}
                  onChange={(event) => setShowPassword(event.target.checked)}
                />
                显示密码
              </label>
            </>
          )}
          {action.kind === 'delete' && (
            <p>
              确认删除账号 <strong>{account?.login_name}</strong>
              ？该账号将无法登录，并从账号列表隐藏。历史记录保留，原账号名不可重复使用。
            </p>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="row account-dialog-actions">
            <button type="button" onClick={onClose} disabled={busy}>
              取消
            </button>
            <button
              type="submit"
              className={action.kind === 'delete' ? 'danger' : 'primary'}
              disabled={busy}
            >
              {busy ? '正在提交…' : actionTitles[action.kind]}
            </button>
          </div>
        </div>
      </Form>
    </dialog>
  );
}
