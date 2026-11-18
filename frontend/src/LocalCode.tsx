import { useEffect, useRef, useState } from 'react';
import type { User } from './Auth';
import type { Project } from './Projects';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { Select } from './FormSelect';
import { Icon } from './Icon';
import { DirectoryPicker } from './FilePicker';
import {
  bindingKey,
  listLocalSources,
  localError,
  localKinds,
  saveLocalSource,
} from './localCodeApi';
import type { LocalSource } from './localCodeApi';
import {
  authorizeDirectory,
  chooseDirectory,
  directorySupported,
  inScope,
  readSelection,
  scanDirectory,
} from './localCodeFiles';
import type { DirectoryHandle, DirectoryTree } from './localCodeFiles';
import {
  appendSnapshot,
  bindDirectory,
  loadBinding,
  loadSnapshot,
  readHistory,
  snapshotName,
} from './localCodeStore';
import type { Binding, Snapshot, SnapshotSummary } from './localCodeStore';

type Props = { project: Project; user: User; onSessionEnd: () => void };

export function LocalCode({ project, user, onSessionEnd }: Props) {
  const [sources, setSources] = useState<LocalSource[]>([]);
  const [bindings, setBindings] = useState<Record<string, Binding | undefined>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<LocalSource | 'new' | null>(null);
  const [history, setHistory] = useState<LocalSource | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => running.current?.abort(), []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError('');
    void (async () => {
      try {
        const items = await listLocalSources(project.id, abort.signal);
        const local: Record<string, Binding | undefined> = {};
        for (const item of items.filter((s) => s.owner_id === user.id)) {
          local[item.client_id] = await loadBinding(
            bindingKey(user.id, project.id, item.client_id),
          );
        }
        if (!abort.signal.aborted) {
          setSources(items);
          setBindings(local);
        }
      } catch (failure) {
        if (!abort.signal.aborted) setError(localError(failure, onSessionEnd));
      } finally {
        if (!abort.signal.aborted) setLoading(false);
      }
    })();
    return () => abort.abort();
  }, [project.id, user.id, revision, onSessionEnd]);

  async function reauthorize(source: LocalSource) {
    if (running.current) return;
    const controller = new AbortController();
    running.current = controller;
    setBusy(source.id);
    setError('');
    setNotice('');
    try {
      const old = bindings[source.client_id];
      // Invoke the permission UI directly from the click, before network or IndexedDB awaits.
      const selected = old
        ? authorizeDirectory(old.handle).then(() => old.handle)
        : chooseDirectory();
      const handle = await selected;
      if (handle.name !== source.directory_name) throw new Error('directory_mismatch');
      const items = await listLocalSources(project.id, controller.signal);
      if (!items.some((s) => s.id === source.id && s.owner_id === user.id))
        throw new Error('project_not_found');
      controller.signal.throwIfAborted();
      await bindDirectory(
        bindingKey(user.id, project.id, source.client_id),
        handle,
        old?.scope || [],
      );
      setNotice(
        old
          ? '目录已重新授权。'
          : '目录已在此浏览器授权，请编辑并选择读取范围；此浏览器会建立新的读取基准。',
      );
      setRevision((v) => v + 1);
    } catch (failure) {
      if (!controller.signal.aborted) setError(localError(failure, onSessionEnd));
    } finally {
      running.current = null;
      setBusy(null);
    }
  }

  async function refresh(source: LocalSource) {
    if (running.current) return;
    const controller = new AbortController();
    running.current = controller;
    setBusy(source.id);
    setError('');
    setNotice('');
    try {
      const key = bindingKey(user.id, project.id, source.client_id);
      const binding = await loadBinding(key);
      if (!binding || !binding.scope.length) {
        setEditor(source);
        return;
      }
      const startedAt = new Date().toISOString();
      const authorized = await listLocalSources(project.id, controller.signal);
      if (!authorized.some((s) => s.id === source.id && s.owner_id === user.id))
        throw new Error('project_not_found');
      const tree = await scanDirectory(binding.handle, controller.signal);
      const result = await readSelection(tree, binding.scope, controller.signal);
      await listLocalSources(project.id, controller.signal);
      controller.signal.throwIfAborted();
      const snapshot = await appendSnapshot(binding, result, binding.scope, startedAt);
      setNotice(
        `快照 ${snapshotName(snapshot)}（#${snapshot.sequence}）已保存到本浏览器，${snapshot.changes.length} 项变化或待比较，未上传代码。`,
      );
      setRevision((v) => v + 1);
      setHistory(source);
    } catch (failure) {
      if (!controller.signal.aborted) setError(localError(failure, onSessionEnd));
    } finally {
      running.current = null;
      setBusy(null);
    }
  }

  return (
    <>
      <div className="between mb">
        <h2>本地代码</h2>
        {project.can_manage && (
          <button
            className="primary"
            disabled={busy !== null || !directorySupported()}
            onClick={() => setEditor('new')}
          >
            ＋ 添加本地目录
          </button>
        )}
      </div>
      <p className="hint">授权本机目录，所选代码和读取历史仅保存在当前浏览器。</p>
      {!directorySupported() && (
        <p className="form-error mt" role="status">
          当前浏览器不支持目录授权，请使用支持此功能的Chrome或Edge，通过HTTPS或本机地址访问。
        </p>
      )}
      <p className="hint mt">仅授权人可读取；换设备需重新授权，清除网站数据会丢失本地历史。</p>
      {error && (
        <div role="alert" className="form-error mt">
          {error}
          <button
            className="ghost small"
            onClick={() => setRevision((v) => v + 1)}
            disabled={busy !== null}
          >
            重新加载
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="account-notice mt">
          {notice}
        </p>
      )}
      {loading ? (
        <p role="status" className="muted mt">
          正在加载目录关联…
        </p>
      ) : (
        <div className="mt">
          {sources.map((source) => (
            <div key={source.id} className="local-source-card panel panel-pad mb">
              <Icon name="folder" />
              <div className="grow">
                <div className="row">
                  <strong>{source.name}</strong>
                  <span className="badge">用户本地目录</span>
                </div>
                <p className="hint">{source.directory_name}</p>
                <p className="hint">
                  {localKinds.find(([k]) => k === source.kind)?.[1]} ·{' '}
                  {source.owner_id === user.id
                    ? `本浏览器 ${bindings[source.client_id]?.sequence || 0} 次读取`
                    : '其他用户授权的目录'}
                </p>
              </div>
              {source.owner_id === user.id && (
                <div className="row local-actions">
                  <button disabled={busy !== null} onClick={() => setHistory(source)}>
                    读取变化记录
                  </button>
                  {project.can_manage && (
                    <>
                      <button
                        disabled={busy !== null || !directorySupported()}
                        onClick={() => void reauthorize(source)}
                      >
                        {bindings[source.client_id] ? '重新授权' : '在此浏览器授权'}
                      </button>
                      <button
                        disabled={busy !== null || !bindings[source.client_id]}
                        onClick={() => void refresh(source)}
                      >
                        {busy === source.id ? '正在读取…' : '读取最新内容'}
                      </button>
                      <button disabled={busy !== null} onClick={() => setEditor(source)}>
                        编辑目录
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
          {!sources.length && !error && (
            <div className="empty">
              <h3>尚未关联本地代码</h3>
              <p>添加自己电脑上的目录，选择需要读取的文件。</p>
            </div>
          )}
        </div>
      )}
      <p className="hint mt">仅点击读取时检查变化，显示发现时间。</p>
      {editor && (
        <LocalEditor
          {...{ project, user, onSessionEnd }}
          source={editor === 'new' ? undefined : editor}
          sources={sources}
          onClose={() => setEditor(null)}
          onSaved={() => {
            setEditor(null);
            setRevision((v) => v + 1);
            setNotice('目录和本次读取记录已保存，代码未上传。');
          }}
        />
      )}
      {history && (
        <LocalHistory source={history} userId={user.id} onClose={() => setHistory(null)} />
      )}
    </>
  );
}

function LocalEditor({
  project,
  user,
  source,
  sources,
  onClose,
  onSaved,
  onSessionEnd,
}: Props & {
  source?: LocalSource;
  sources: LocalSource[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [clientId] = useState(() => source?.client_id || crypto.randomUUID());
  const key = bindingKey(user.id, project.id, clientId);
  const [name, setName] = useState(source?.name || '');
  const [kind, setKind] = useState(source?.kind || 'BACKEND');
  const [handle, setHandle] = useState<DirectoryHandle>();
  const [tree, setTree] = useState<DirectoryTree>();
  const [scope, setScope] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [savedSource, setSavedSource] = useState(source);
  const [loaded, setLoaded] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    void loadBinding(key)
      .then((binding) => {
        if (!abort.signal.aborted) {
          setHandle(binding?.handle);
          setScope(binding?.scope || []);
          setLoaded(true);
        }
      })
      .catch((failure) => {
        if (!abort.signal.aborted) setError(localError(failure, onSessionEnd));
      });
    return () => abort.abort();
  }, [key, onSessionEnd]);

  async function choose() {
    setBusy(true);
    setError('');
    try {
      const chosen = await chooseDirectory();
      if (handle && !(await handle.isSameEntry(chosen))) throw new Error('directory_mismatch');
      if (source && chosen.name !== source.directory_name) throw new Error('directory_mismatch');
      for (const existing of sources.filter(
        (item) => item.owner_id === user.id && item.client_id !== clientId,
      )) {
        const linked = await loadBinding(bindingKey(user.id, project.id, existing.client_id));
        if (linked && (await linked.handle.isSameEntry(chosen)))
          throw new Error('local_directory_duplicate');
      }
      if (controller.current.signal.aborted) return;
      setHandle(chosen);
      setTree(undefined);
      if (!name) setName(chosen.name);
    } catch (failure) {
      setError(localError(failure, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  async function scan() {
    if (!handle) return;
    setBusy(true);
    setError('');
    try {
      await authorizeDirectory(handle);
      const found = await scanDirectory(handle, controller.current.signal);
      if (!controller.current.signal.aborted) setTree(found);
    } catch (failure) {
      if (!controller.current.signal.aborted) setError(localError(failure, onSessionEnd));
    } finally {
      setBusy(false);
    }
  }
  function toggle(path: string, checked: boolean) {
    if (checked)
      setScope((old) => [
        ...old.filter((p) => !p.startsWith(path.endsWith('/') ? path : path + '/')),
        path,
      ]);
    else
      setScope((old) =>
        (tree?.files || [])
          .filter((entry) => inScope(entry.path, old) && !inScope(entry.path, [path]))
          .map((entry) => entry.path),
      );
  }
  return (
    <CaseDialog
      title={source ? '编辑本地代码目录' : '添加本地代码目录'}
      busy={busy}
      onClose={onClose}
      wide
    >
      <Form
        className="stack"
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy || !handle || !tree || !scope.length) return;
          setBusy(true);
          setError('');
          try {
            const startedAt = new Date().toISOString();
            const previousBinding = await loadBinding(key);
            // Always enumerate again at submit time; the preview is not the read snapshot.
            const latest = await scanDirectory(handle, controller.current.signal);
            const contents = await readSelection(latest, scope, controller.current.signal);
            controller.current.signal.throwIfAborted();
            const saved = await saveLocalSource(project.id, {
              client_id: clientId,
              name,
              directory_name: handle.name,
              kind,
              version: savedSource?.version || 0,
            });
            if (saved.owner_id !== user.id) throw new Error('invalid_response');
            setSavedSource(saved);
            await bindDirectory(key, handle, scope);
            const binding = await loadBinding(key);
            if (!binding) throw new Error('local_storage_unavailable');
            if (previousBinding && binding.sequence !== previousBinding.sequence)
              throw new Error('local_read_conflict');
            controller.current.signal.throwIfAborted();
            await appendSnapshot(binding, contents, scope, startedAt);
            onSaved();
          } catch (failure) {
            if (!controller.current.signal.aborted) setError(localError(failure, onSessionEnd));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="account-form-grid">
          <label className="form-field">
            来源名称
            <input
              required
              maxLength={80}
              value={name}
              disabled={busy}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="form-field">
            代码类型
            <Select value={kind} disabled={busy} onChange={setKind}>
              {localKinds.map(([v, title]) => (
                <option key={v} value={v}>
                  {title}
                </option>
              ))}
            </Select>
          </label>
        </div>
        <label className="form-field">
          读取方式
          <input readOnly value="按需读取最新内容，自动记录变化" />
        </label>
        <div className="form-field">
          <span>本地目录</span>
          <div className="row">
            <span className="local-directory grow">
              {handle?.name || source?.directory_name || '尚未选择自己的目录'}
            </span>
            <DirectoryPicker
              disabled={busy || !loaded || !directorySupported()}
              onClick={() => void choose()}
            />
            <button type="button" disabled={busy || !handle} onClick={() => void scan()}>
              读取文件树 / 授权
            </button>
          </div>
        </div>
        <p className="hint">选择目录后勾选读取范围；新目录请新建来源。</p>
        {tree ? (
          <section className="panel panel-pad">
            <div className="between">
              <h3>文件树与读取范围</h3>
              <span className="badge">
                {tree.files.length} 个文件 · 已排除 {tree.excluded} 项
              </span>
            </div>
            <label className="form-field mt">
              搜索路径
              <input value={search} onChange={(e) => setSearch(e.target.value)} disabled={busy} />
            </label>
            <label className="row mt">
              <input
                type="checkbox"
                checked={scope.includes('/')}
                disabled={busy}
                onChange={(e) => setScope(e.target.checked ? ['/'] : [])}
              />
              选择整个目录（含后续新增文件，仍排除敏感及构建文件）
            </label>
            <div className="local-file-tree mt">
              <FileTree tree={tree} scope={scope} search={search} disabled={busy} toggle={toggle} />
            </div>
            {!tree.files.length && <p className="hint">此目录没有可选择的文件。</p>}
            <p className="hint mt">
              已选{tree.files.filter((entry) => inScope(entry.path, scope)).length}
              个当前文件；勾选目录包含后续新增文件。
            </p>
            <p className="hint">范围：{scope.join('、') || '尚未勾选'}</p>
          </section>
        ) : (
          <p className="hint">尚未读取文件树。没有扫描完成前不能保存读取记录。</p>
        )}
        <p className="hint">
          默认排除凭据、依赖、构建产物和二进制文件；无法读取的文件不会记为删除。
        </p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="row">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="primary" disabled={busy || !tree || !scope.length}>
            {busy ? '正在处理…' : '保存目录与本次读取'}
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}

function FileTree({
  tree,
  scope,
  search,
  disabled,
  toggle,
}: {
  tree: DirectoryTree;
  scope: string[];
  search: string;
  disabled: boolean;
  toggle: (path: string, checked: boolean) => void;
}) {
  const paths = [...tree.directories, ...tree.files.map((entry) => entry.path)];
  function render(prefix: string): React.ReactNode {
    return paths
      .filter(
        (path) =>
          path !== prefix &&
          path.startsWith(prefix) &&
          !path.slice(prefix.length).replace(/\/$/, '').includes('/'),
      )
      .filter(
        (path) =>
          path.toLowerCase().includes(search.toLowerCase()) ||
          (path.endsWith('/') &&
            paths.some(
              (child) =>
                child.startsWith(path) && child.toLowerCase().includes(search.toLowerCase()),
            )),
      )
      .sort()
      .map((path) =>
        path.endsWith('/') ? (
          <details key={path} open={search ? true : undefined}>
            <summary>{path.slice(prefix.length)}</summary>
            <label className="row">
              <input
                type="checkbox"
                disabled={disabled}
                checked={inScope(path, scope)}
                onChange={(e) => toggle(path, e.target.checked)}
              />
              选择此目录（含新增文件）
            </label>
            <div className="local-tree-indent">{render(path)}</div>
          </details>
        ) : (
          <label key={path} className="row local-file-row">
            <input
              type="checkbox"
              disabled={disabled}
              checked={inScope(path, scope)}
              onChange={(e) => toggle(path, e.target.checked)}
            />
            <span>{path.slice(prefix.length)}</span>
          </label>
        ),
      );
  }
  return <>{render('')}</>;
}

function LocalHistory({
  source,
  userId,
  onClose,
}: {
  source: LocalSource;
  userId: number;
  onClose: () => void;
}) {
  const key = bindingKey(userId, source.project_id, source.client_id);
  const [rows, setRows] = useState<SnapshotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<{ current: Snapshot; previous?: Snapshot }>();
  const [page, setPage] = useState(Number.MAX_SAFE_INTEGER);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const generation = useRef({ value: 0 });
  useEffect(() => {
    let active = true;
    const counter = generation.current;
    setLoading(true);
    setDetail(undefined);
    setError('');
    void readHistory(key, page)
      .then((result) => {
        if (active) setRows(result);
      })
      .catch((failure) => {
        if (active) setError(localError(failure, () => {}));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      counter.value++;
    };
  }, [key, page]);
  async function openRecord(sequence: number) {
    const currentGeneration = ++generation.current.value;
    setLoadingDetail(true);
    setError('');
    try {
      const current = await loadSnapshot(key, sequence);
      const previous = sequence > 1 ? await loadSnapshot(key, sequence - 1) : undefined;
      if (!current || (sequence > 1 && !previous)) throw new Error('local_history_missing');
      if (currentGeneration === generation.current.value) setDetail({ current, previous });
    } catch (failure) {
      if (currentGeneration === generation.current.value) setError(localError(failure, () => {}));
    } finally {
      if (currentGeneration === generation.current.value) setLoadingDetail(false);
    }
  }
  return (
    <CaseDialog title={`读取变化记录 · ${source.name}`} busy={false} onClose={onClose} wide>
      <p className="hint">显示本浏览器的读取历史，时间为发现时间。</p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status">正在加载本地记录…</p>
      ) : rows.length ? (
        <div className="stack mt">
          {rows.map((row) => (
            <div className="between" key={row.sequence}>
              <span>
                {snapshotName(row)} · #{row.sequence} · {row.changes.length} 项变化或待比较
              </span>
              <button disabled={loadingDetail} onClick={() => void openRecord(row.sequence)}>
                查看内容与差异
              </button>
            </div>
          ))}
          <div className="row">
            <button
              disabled={page === Number.MAX_SAFE_INTEGER}
              onClick={() => setPage(Number.MAX_SAFE_INTEGER)}
            >
              最新记录
            </button>
            <button
              disabled={rows.length < 20}
              onClick={() => setPage(rows[rows.length - 1].sequence)}
            >
              更早记录
            </button>
          </div>
        </div>
      ) : (
        <div className="empty">
          <h3>此浏览器暂无读取记录</h3>
          <p>授权并读取后建立本地基准，其他电脑或浏览器的历史不会自动同步。</p>
        </div>
      )}
      {detail && (
        <section className="mt">
          <h3>
            {snapshotName(detail.current)} · #{detail.current.sequence}
          </h3>
          <p className="hint">
            读取开始：{new Date(detail.current.startedAt).toLocaleString('zh-CN')} · 完成：
            {new Date(detail.current.foundAt).toLocaleString('zh-CN')}
          </p>
          {!detail.current.changes.length && (
            <p className="account-notice mt">与上次读取内容一致，未发现变化。</p>
          )}
          {detail.current.changes.map((change) => (
            <details className="panel panel-pad mt" key={change.path}>
              <summary>
                {change.kind} · {change.path}
              </summary>
              <div className="local-diff-grid mt">
                <div>
                  <h3>上次读取</h3>
                  <pre>
                    {detail.previous?.files[change.path]?.content ??
                      detail.previous?.skipped[change.path] ??
                      '文件不存在或未纳入范围'}
                  </pre>
                </div>
                <div>
                  <h3>本次读取</h3>
                  <pre>
                    {detail.current.files[change.path]?.content ??
                      detail.current.skipped[change.path] ??
                      '文件不存在或未纳入范围'}
                  </pre>
                </div>
              </div>
            </details>
          ))}
          <details className="mt">
            <summary>本次完整快照（{Object.keys(detail.current.files).length} 个文件）</summary>
            {Object.entries(detail.current.files).map(([path, file]) => (
              <details className="mt" key={path}>
                <summary>
                  {path} · {file.size} 字节
                </summary>
                <pre className="local-code-preview">{file.content}</pre>
              </details>
            ))}
          </details>
        </section>
      )}
    </CaseDialog>
  );
}
