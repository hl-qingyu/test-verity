import { CaseDialog } from './CaseDialog';
import { useCachedView } from './pageViewCache';
import type { PageViewCache } from './pageViewCache';
import { Form } from './Form';
import { Select } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import type { User } from './Auth';
import { apiRequest } from './api/http';
import { requestError } from './projectApi';
import type { GitHubConnection } from './githubApi';
import { LocalCode } from './LocalCode';

export type Project = {
  id: number;
  name: string;
  identifier: string;
  description: string;
  owner_id: number;
  owner_name: string;
  version: number;
  can_manage: boolean;
};
type Repository = {
  id: number;
  github_id: number;
  full_name: string;
  url: string;
  kind: string;
  default_branch: string;
  version: number;
  has_personal_authorization: boolean;
};
type Member = { id: number; name: string; role: string; status: string };
const kinds = [
  ['BACKEND', '后端'],
  ['WEB', '前端'],
  ['FLUTTER', '移动端'],
  ['PROTOTYPE', '原型'],
  ['OTHER', '其他'],
];

function readSelectedProject(userId: number): number | null {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(`verity-selected-project:${userId}`) || 'null',
    );
    return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function useProjects(userId: number, onSessionEnd: () => void) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState<number | null>(() => readSelectedProject(userId));
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    apiRequest<Project[]>('/api/projects', { signal: controller.signal })
      .then((items) => {
        if (controller.signal.aborted) return;
        setProjects(items);
        setSelected((id) => (items.some((p) => p.id === id) ? id : items[0]?.id || null));
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(requestError(e, onSessionEnd));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision, onSessionEnd]);
  useEffect(() => {
    // Persist only after the server has confirmed the user's visible projects.
    if (loading || error || (selected !== null && !projects.some((p) => p.id === selected))) return;
    try {
      const key = `verity-selected-project:${userId}`;
      if (selected === null) localStorage.removeItem(key);
      else localStorage.setItem(key, String(selected));
    } catch {
      // Project switching remains usable when browser storage is unavailable.
    }
  }, [userId, selected, projects, loading, error]);
  return {
    projects,
    selected,
    setSelected,
    current: projects.find((p) => p.id === selected) || null,
    loading,
    error,
    reload: () => setRevision((v) => v + 1),
  };
}

function PersonPicker({
  value,
  onChange,
  disabled,
  currentName,
  onSessionEnd,
}: {
  value: number;
  onChange: (id: number) => void;
  disabled: boolean;
  currentName?: string;
  onSessionEnd: () => void;
}) {
  const [search, setSearch] = useState('');
  const [people, setPeople] = useState<{ id: number; name: string; login_name: string }[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      apiRequest<typeof people>(`/api/projects/people?search=${encodeURIComponent(search)}`, {
        signal: controller.signal,
      })
        .then((items) => {
          setPeople(items);
          setError('');
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(requestError(e, onSessionEnd));
        });
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [search, onSessionEnd]);
  return (
    <div className="stack">
      <label className="form-field">
        负责人账号
        <Select
          required
          search={search}
          onSearchChange={setSearch}
          value={value || ''}
          disabled={disabled}
          onChange={(e) => onChange(Number(e))}
        >
          <option value="">请选择</option>
          {value && !people.some((p) => p.id === value) && (
            <option value={value}>{currentName || '已选择账号'}</option>
          )}
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}（{p.login_name}）
            </option>
          ))}
        </Select>
      </label>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function ProjectForm({
  project,
  user,
  onSaved,
  onSessionEnd,
}: {
  project: Project | null;
  user: User;
  onSaved: (project: Project) => void;
  onSessionEnd: () => void;
}) {
  const [name, setName] = useState(project?.name || '');
  const [description, setDescription] = useState(project?.description || '');
  const [owner, setOwner] = useState(
    project?.owner_id || (user.platform_role === 'ADMIN' ? 0 : user.id),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const readonly = project ? !project.can_manage : false;
  return (
    <Form
      className="stack"
      validationMessage="请填写项目名称并选择项目负责人，项目名称最多80个字符。"
      onInput={() => setError('')}
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy || readonly) return;
        setBusy(true);
        setError('');
        setNotice('');
        try {
          const result = await apiRequest<Project>(
            project ? `/api/projects/${project.id}` : '/api/projects',
            {
              method: project ? 'PATCH' : 'POST',
              body: JSON.stringify({
                name,
                description,
                owner_id: owner,
                version: project?.version || 0,
              }),
            },
          );
          onSaved(result);
          setNotice('项目信息已保存。');
        } catch (err) {
          setError(requestError(err, onSessionEnd));
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="form-field">
        项目名称（必填）
        <input
          required
          maxLength={80}
          value={name}
          disabled={busy || readonly}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      {project && (
        <label className="form-field">
          项目标识（系统生成）
          <input readOnly value={project.identifier} />
        </label>
      )}
      <div className="form-field">项目负责人（必填）</div>
      {user.platform_role === 'ADMIN' ? (
        <PersonPicker
          value={owner}
          onChange={setOwner}
          disabled={busy}
          currentName={project?.owner_name}
          onSessionEnd={onSessionEnd}
        />
      ) : (
        <p>{project?.owner_name || `${user.display_name}（本人）`}</p>
      )}
      {!project && user.platform_role !== 'ADMIN' && (
        <p className="hint">创建后你将成为项目负责人。</p>
      )}
      <label className="form-field">
        项目说明
        <textarea
          rows={5}
          maxLength={2000}
          value={description}
          disabled={busy || readonly}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
      {!readonly && (
        <button className="primary" disabled={busy || !owner}>
          {busy ? '正在保存…' : project ? '保存项目' : '创建项目'}
        </button>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="account-notice" role="status">
          {notice}
        </p>
      )}
    </Form>
  );
}

export function CreateProjectDialog({
  user,
  onClose,
  onCreated,
  onSessionEnd,
}: {
  user: User;
  onClose: () => void;
  onCreated: (project: Project) => void;
  onSessionEnd: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const backdropPressed = useRef(false);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="account-dialog"
      onCancel={onClose}
      onPointerDown={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        backdropPressed.current =
          event.target === event.currentTarget &&
          (event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom);
      }}
      onClick={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        const outside =
          event.target === event.currentTarget &&
          (event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom);
        if (backdropPressed.current && outside) onClose();
        backdropPressed.current = false;
      }}
      aria-labelledby="new-project-title"
    >
      <div className="panel-head">
        <h2 id="new-project-title">新建项目</h2>
        <button onClick={onClose} aria-label="关闭">
          ×
        </button>
      </div>
      <div className="panel-pad">
        <ProjectForm project={null} user={user} onSaved={onCreated} onSessionEnd={onSessionEnd} />
      </div>
    </dialog>
  );
}

export function ProjectSettings({
  project,
  user,
  onChanged,
  onSessionEnd,
  pageCache,
}: {
  pageCache?: PageViewCache;
  project: Project | null;
  user: User;
  onChanged: () => void;
  onSessionEnd: () => void;
}) {
  const [tab, setTab] = useCachedView(pageCache, 'tab', 'repos');
  const [deleting, setDeleting] = useState(false),
    [deleteBusy, setDeleteBusy] = useState(false),
    [deleteError, setDeleteError] = useState('');
  const deleteLock = useRef(false);
  const sections = [
    ['general', '基本信息'],
    ['repos', 'GitHub 仓库'],
    ['local-code', '本地代码'],
    ['members', '成员与权限'],
  ];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>项目设置</h1>
        </div>
      </div>
      {!project ? (
        <section className="panel empty">
          <h2>尚未选择项目</h2>
          <p>点击左侧“＋”创建项目。</p>
        </section>
      ) : (
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="项目设置分类">
            {sections.map(([key, title]) => (
              <button
                key={key}
                className={tab === key ? 'active' : ''}
                aria-current={tab === key ? 'page' : undefined}
                onClick={() => setTab(key)}
              >
                {title}
              </button>
            ))}
          </nav>
          <section className="panel panel-pad">
            {!project.can_manage && (
              <p className="hint mb">当前为项目成员，可查看配置；修改需负责人或管理员。</p>
            )}
            {tab === 'general' ? (
              <>
                <ProjectForm
                  key={`${project.id}-${project.version}`}
                  project={project}
                  user={user}
                  onSaved={onChanged}
                  onSessionEnd={onSessionEnd}
                />
                {project.can_manage && (
                  <div className="project-delete-section">
                    <div>
                      <h3>删除项目</h3>
                    </div>
                    <button
                      className="danger"
                      onClick={() => {
                        setDeleteError('');
                        setDeleting(true);
                      }}
                    >
                      删除项目
                    </button>
                  </div>
                )}
              </>
            ) : tab === 'repos' ? (
              <ProjectRepositories project={project} onSessionEnd={onSessionEnd} />
            ) : tab === 'members' ? (
              <ProjectMembers project={project} onChanged={onChanged} onSessionEnd={onSessionEnd} />
            ) : tab === 'local-code' ? (
              <LocalCode
                key={`${user.id}-${project.id}`}
                project={project}
                user={user}
                onSessionEnd={onSessionEnd}
              />
            ) : null}
          </section>
        </div>
      )}
      {project && deleting && (
        <CaseDialog
          key={project.id}
          title="删除项目"
          busy={deleteBusy}
          onClose={() => setDeleting(false)}
          footer={
            <footer className="change-dialog-footer">
              <button disabled={deleteBusy} onClick={() => setDeleting(false)}>
                取消
              </button>
              <button
                className="danger"
                disabled={deleteBusy}
                onClick={async () => {
                  if (deleteLock.current) return;
                  deleteLock.current = true;
                  setDeleteBusy(true);
                  setDeleteError('');
                  try {
                    await apiRequest(`/api/projects/${project.id}`, {
                      method: 'DELETE',
                      body: JSON.stringify({ version: project.version, confirmed: true }),
                    });
                    setDeleting(false);
                    onChanged();
                  } catch (e) {
                    setDeleteError(requestError(e, onSessionEnd));
                  } finally {
                    deleteLock.current = false;
                    setDeleteBusy(false);
                  }
                }}
              >
                {deleteBusy ? '正在删除…' : '确认删除'}
              </button>
            </footer>
          }
        >
          <p>确认删除项目“{project.name}”？</p>
          <p className="hint mt">
            删除后项目从列表隐藏，所有成员均无法继续访问。资料、用例、历史报告及审核记录保留，不删除远端仓库或本地代码文件。
          </p>
          <p className="hint mt">
            有排队或执行中的分析、对话、审核入库任务时不能删除，请等待任务结束或在对应模块取消。
          </p>
          {deleteError && (
            <p className="form-error mt" role="alert">
              {deleteError}
            </p>
          )}
        </CaseDialog>
      )}
    </>
  );
}

function ProjectMembers({
  project,
  onChanged,
  onSessionEnd,
}: {
  project: Project;
  onChanged: () => void;
  onSessionEnd: () => void;
}) {
  const [data, setData] = useState<{ version: number; items: Member[] } | null>(null);
  const [selected, setSelected] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    apiRequest<typeof data>(`/api/projects/${project.id}/members`, { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(requestError(e, onSessionEnd));
      });
    return () => controller.abort();
  }, [project.id, revision, onSessionEnd]);
  async function update(remove?: number) {
    if (!data || busy) return;
    setBusy(true);
    setError('');
    try {
      await apiRequest(
        remove
          ? `/api/projects/${project.id}/members/${remove}?version=${data.version}`
          : `/api/projects/${project.id}/members`,
        {
          method: remove ? 'DELETE' : 'POST',
          body: remove ? undefined : JSON.stringify({ user_id: selected, version: data.version }),
        },
      );
      setRevision((v) => v + 1);
      onChanged();
      setSelected(0);
    } catch (e) {
      setError(requestError(e, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h2>项目成员</h2>
      {data?.items.map((m) => (
        <div className="row between mt" key={m.id}>
          <span>
            {m.name} · {m.role}
            {m.status !== 'ACTIVE' ? '（账号不可用）' : ''}
          </span>
          {project.can_manage && m.role !== '负责人' && (
            <button disabled={busy} onClick={() => void update(m.id)}>
              移除成员
            </button>
          )}
        </div>
      ))}
      {project.can_manage && (
        <Form
          className="stack mt"
          onSubmit={(e) => {
            e.preventDefault();
            void update();
          }}
        >
          <h3>添加成员</h3>
          <PersonPicker
            value={selected}
            onChange={setSelected}
            disabled={busy}
            onSessionEnd={onSessionEnd}
          />
          <button disabled={busy || !selected || !data} className="primary">
            添加成员
          </button>
        </Form>
      )}
      {error && (
        <p className="form-error mt" role="alert">
          {error}
        </p>
      )}
      <button
        className="small mt"
        disabled={busy}
        onClick={() => {
          setError('');
          setRevision((v) => v + 1);
        }}
      >
        刷新成员
      </button>
    </>
  );
}

function ProjectRepositories({
  project,
  onSessionEnd,
}: {
  project: Project;
  onSessionEnd: () => void;
}) {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [deleting, setDeleting] = useState<Repository | null>(null);
  const [deletingBusy, setDeletingBusy] = useState(false);
  const [connections, setConnections] = useState<GitHubConnection[]>([]);
  const [dialog, setDialog] = useState<{ repository: Repository | null } | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    Promise.all([
      apiRequest<Repository[]>(`/api/projects/${project.id}/repositories`, {
        signal: controller.signal,
      }),
      apiRequest<GitHubConnection[]>('/api/github/connections', { signal: controller.signal }),
    ])
      .then(([r, c]) => {
        setRepos(r);
        setConnections(c);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(requestError(e, onSessionEnd));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [project.id, revision, onSessionEnd]);
  return (
    <>
      <div className="row between">
        <h2>关联 GitHub 仓库</h2>
        {project.can_manage && (
          <button disabled={loading} onClick={() => setDialog({ repository: null })}>
            ＋ 添加仓库
          </button>
        )}
      </div>
      {loading ? (
        <p className="mt" role="status">
          正在加载…
        </p>
      ) : repos.length ? (
        repos.map((r) => (
          <div className="panel panel-pad mt" key={r.id}>
            <div className="row between">
              <h3>{r.full_name}</h3>
              {project.can_manage && (
                <div className="row">
                  <button onClick={() => setDialog({ repository: r })}>编辑</button>
                  <button
                    className="danger"
                    onClick={() => {
                      setError('');
                      setDeleting(r);
                    }}
                  >
                    删除
                  </button>
                </div>
              )}
            </div>
            <p className="hint mt">{r.url}</p>
            <p className="hint">
              {kinds.find(([v]) => v === r.kind)?.[1]} · {r.default_branch}
            </p>
            <p className="hint">
              {r.has_personal_authorization
                ? '本人已有仓库授权配置（未实时核验）'
                : '本人尚未配置此仓库的读取授权'}
            </p>
          </div>
        ))
      ) : (
        <p className="muted mt">尚未关联仓库。</p>
      )}
      <p className="hint mt">项目成员读取仓库时使用各自连接。</p>
      {error && (
        <p className="form-error mt" role="alert">
          {error}
        </p>
      )}
      <button className="small mt" onClick={() => setRevision((v) => v + 1)}>
        刷新仓库
      </button>
      {deleting && (
        <CaseDialog title="删除项目仓库关联" busy={deletingBusy} onClose={() => setDeleting(null)}>
          <p>
            确认从项目“{project.name}”移除仓库“{deleting.full_name}
            ”？仅移除本项目关联，不删除远端仓库、个人连接或其他项目的关联。
          </p>
          <p className="hint mt">仍被原型资料或历史来源引用的关联不能删除。</p>
          {error && (
            <p className="form-error mt" role="alert">
              {error}
            </p>
          )}
          <div className="row mt">
            <button disabled={deletingBusy} onClick={() => setDeleting(null)}>
              取消
            </button>
            <button
              className="danger"
              disabled={deletingBusy}
              onClick={async () => {
                setDeletingBusy(true);
                setError('');
                try {
                  await apiRequest(`/api/projects/${project.id}/repositories/${deleting.id}`, {
                    method: 'DELETE',
                    body: JSON.stringify({ version: deleting.version, confirmed: true }),
                  });
                  setDeleting(null);
                  setRevision((v) => v + 1);
                } catch (e) {
                  setError(requestError(e, onSessionEnd));
                } finally {
                  setDeletingBusy(false);
                }
              }}
            >
              {deletingBusy ? '正在删除…' : '确认移除关联'}
            </button>
          </div>
        </CaseDialog>
      )}
      {dialog && (
        <RepositoryDialog
          repository={dialog.repository}
          project={project}
          connections={connections}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            setRevision((v) => v + 1);
          }}
          onSessionEnd={onSessionEnd}
        />
      )}
    </>
  );
}

function RepositoryDialog({
  repository,
  project,
  connections,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  repository: Repository | null;
  project: Project;
  connections: GitHubConnection[];
  onClose: () => void;
  onSaved: () => void;
  onSessionEnd: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const initial = connections.find((c) =>
    c.repositories.some((r) => r.github_id === repository?.github_id),
  );
  const [connectionId, setConnectionId] = useState(initial?.id || 0);
  const [githubId, setGithubId] = useState(initial ? repository?.github_id || 0 : 0);
  const [kind, setKind] = useState(repository?.kind || 'BACKEND');
  const [branch, setBranch] = useState(repository?.default_branch || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const connection = connections.find((c) => c.id === connectionId);
  const repo = connection?.repositories.find((r) => r.github_id === githubId);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="account-dialog"
      aria-labelledby="repo-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <Form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          setBusy(true);
          setError('');
          try {
            await apiRequest(`/api/projects/${project.id}/repositories`, {
              method: 'POST',
              body: JSON.stringify({
                association_id: repository?.id || null,
                connection_id: connectionId,
                github_id: githubId,
                kind,
                default_branch: branch,
                version: repository?.version || 0,
              }),
            });
            onSaved();
          } catch (err) {
            setError(requestError(err, onSessionEnd));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="panel-head">
          <h2 id="repo-title">{repository ? '编辑仓库' : '关联 GitHub 仓库'}</h2>
          <button type="button" disabled={busy} onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <div className="panel-pad stack">
          <p className="hint">当前项目：{project.name}。请选择本人连接中已授权的仓库。</p>
          {!connections.length && (
            <p className="hint">请先在平台设置 → GitHub 连接中配置自己的连接。</p>
          )}
          <label className="form-field">
            GitHub 连接
            <Select
              required
              value={connectionId || ''}
              disabled={busy}
              onChange={(e) => {
                setConnectionId(Number(e));
                setGithubId(0);
                setBranch('');
              }}
            >
              <option value="">请选择自己的连接</option>
              {connections.map((c) => (
                <option value={c.id} key={c.id}>
                  {c.name} · {c.github_login}
                </option>
              ))}
            </Select>
          </label>
          <label className="form-field">
            仓库
            <Select
              required
              value={githubId || ''}
              disabled={busy}
              onChange={(e) => {
                const id = Number(e);
                setGithubId(id);
                setBranch(
                  connection?.repositories.find((r) => r.github_id === id)?.default_branch || '',
                );
              }}
            >
              <option value="">请选择已授权仓库</option>
              {connection?.repositories.map((r) => (
                <option value={r.github_id} key={r.github_id}>
                  {r.full_name}
                </option>
              ))}
            </Select>
          </label>
          <label className="form-field">
            仓库地址
            <input readOnly value={repo ? `https://github.com/${repo.full_name}` : ''} />
          </label>
          <div className="account-form-grid">
            <label className="form-field">
              仓库类型
              <Select value={kind} disabled={busy} onChange={(e) => setKind(e)}>
                {kinds.map(([v, label]) => (
                  <option value={v} key={v}>
                    {label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="form-field">
              默认分支
              <input
                value={branch}
                required
                maxLength={255}
                disabled={busy}
                onChange={(e) => setBranch(e.target.value)}
              />
            </label>
          </div>
          <p className="hint">保存时校验所选分支的访问权限。</p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="row">
            <button type="button" disabled={busy} onClick={onClose}>
              取消
            </button>
            <button className="primary" disabled={busy || !repo}>
              {busy ? '正在验证并保存…' : '保存仓库'}
            </button>
          </div>
        </div>
      </Form>
    </dialog>
  );
}
