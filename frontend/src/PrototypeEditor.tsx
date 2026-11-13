import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { FilePicker } from './FilePicker';
import { CodeFileTree } from './CodeFileTree';
import { directoryArchive, selectedDirectory } from './prototypeDirectory';
import {
  parsePrototypeScope,
  prototypeError,
  prototypeRequest,
  prototypeUrl,
} from './prototypeApi';
import type {
  PrototypeConnection,
  PrototypeLibrary,
  PrototypeScope,
  PrototypeSource,
} from './prototypeApi';

export function PrototypeEditor({
  base,
  kind,
  html = false,
  source,
  library,
  connections,
  onSaved,
  onClose,
  onSessionEnd,
}: {
  base: string;
  kind: PrototypeSource['kind'];
  html?: boolean;
  source?: PrototypeSource;
  library: PrototypeLibrary;
  connections: PrototypeConnection[];
  onSaved: (v: PrototypeLibrary, done: boolean) => void;
  onClose: () => void;
  onSessionEnd: () => void;
}) {
  const directory = kind === 'DIRECTORY';
  const fileLabel = html ? 'HTML 文件' : '图片';
  const first =
    connections.find((c) => c.repositories.some((r) => r.id === source?.repository_id)) ||
    connections[0];
  const [name, setName] = useState(source?.name || ''),
    [description, setDescription] = useState(source?.description || ''),
    [group, setGroup] = useState(String(source?.group_id || '')),
    [url, setUrl] = useState(source?.url || ''),
    [connection, setConnection] = useState(String(first?.id || '')),
    [repository, setRepository] = useState(String(source?.repository_id || '')),
    [branch, setBranch] = useState(source?.branch || 'main'),
    [path, setPath] = useState(source?.path ?? ''),
    [scope, setScope] = useState<PrototypeScope | null>(null),
    [selected, setSelected] = useState<string[]>([]),
    [files, setFiles] = useState<File[]>([]),
    [folder, setFolder] = useState<ReturnType<typeof selectedDirectory> | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const abort = useRef(new AbortController()),
    pending = useRef(false),
    ids = useRef(new Map<File, string>()),
    directoryRequest = useRef<{ signature: string; id: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    abort.current = controller;
    return () => controller.abort();
  }, []);
  const repos = connections.find((c) => c.id === Number(connection))?.repositories || [];
  const selectedSet = new Set(selected);
  const reset = () => {
    setScope(null);
    setSelected([]);
    setError('');
  };
  const git = {
    connection_id: Number(connection),
    repository_id: Number(repository),
    branch,
    path: path.trim(),
  };
  function addFiles(incoming: File[]) {
    if (!busy && incoming.length) setFiles((old) => (source ? incoming : [...old, ...incoming]));
  }
  async function scan() {
    if (pending.current) return;
    if (!connection || !repository || !branch) {
      setError('请选择本人连接、项目仓库并填写分支。');
      return;
    }
    pending.current = true;
    setBusy(true);
    reset();
    try {
      const value = parsePrototypeScope(
        await apiRequest<unknown>(`${base}/scope`, {
          method: 'POST',
          body: JSON.stringify(git),
          signal: abort.current.signal,
          timeoutMs: 120000,
        }),
      );
      if (!abort.current.signal.aborted) {
        setScope(value);
        setSelected(value.files.map((file) => file.path));
      }
    } catch (e) {
      if (!abort.current.signal.aborted) setError(prototypeError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (!abort.current.signal.aborted) setBusy(false);
    }
  }
  async function save() {
    if (pending.current) return;
    if (kind !== 'FILE' && !name.trim()) {
      setError('请填写资料名称。');
      return;
    }
    if (kind === 'LINK' && !prototypeUrl(url)) {
      setError('请输入有效的 HTTP / HTTPS 链接，不包含用户名或密码。');
      return;
    }
    if (kind === 'GITHUB' && (!scope || !selected.length)) {
      setError('请读取文件清单并至少选择一个文件。');
      return;
    }
    if (kind === 'FILE' && (!files.length || (source && files.length !== 1))) {
      setError(`请选择${fileLabel}；更新版本只允许一个文件。`);
      return;
    }
    if (directory && (!folder || !selected.length)) {
      setError('请选择目录，并至少勾选一个可上传的文件。');
      return;
    }
    pending.current = true;
    setBusy(true);
    setError('');
    let completed = 0;
    try {
      if (directory && folder) {
        const entries = folder.entries.filter((e) => selectedSet.has(e.path));
        const signature = JSON.stringify([
          name,
          description,
          group,
          entries.map((e) => [e.path, e.file.size, e.file.lastModified]),
        ]);
        if (directoryRequest.current?.signature !== signature)
          directoryRequest.current = { signature, id: crypto.randomUUID() };
        const query = new URLSearchParams({
          filename: folder.name,
          name: name.trim(),
          description,
          revision: String(library.revision),
          upload_id: directoryRequest.current.id,
        });
        if (group) query.set('group_id', group);
        const value = await prototypeRequest(
          `${base}/directories${source ? `/${source.id}/versions` : ''}?${query}`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-tar' },
            body: directoryArchive(entries, {
              name: name.trim(),
              description,
              group_id: group ? Number(group) : null,
              source_id: source?.id || null,
              directory_name: folder.name,
            }),
            timeoutMs: 1800000,
            signal: abort.current.signal,
          },
        );
        if (!abort.current.signal.aborted) onSaved(value, true);
      } else if (kind === 'FILE') {
        let current = library;
        for (const file of files) {
          if (!(html ? /\.html?$/i : /\.(png|jpe?g|webp)$/i).test(file.name) || !file.size)
            throw new Error('document_format');
          if (!html) {
            const bitmap = await createImageBitmap(file).catch(() => {
              throw new Error('document_format_mismatch');
            });
            bitmap.close();
          }
          if (abort.current.signal.aborted) return;
          if (!ids.current.has(file)) ids.current.set(file, crypto.randomUUID());
          const query = new URLSearchParams({
            filename: file.name,
            revision: String(current.revision),
            upload_id: ids.current.get(file)!,
            name: name.trim()
              ? files.length === 1
                ? name.trim()
                : `${name.trim()} · ${file.name}`
              : file.name,
            description,
          });
          if (source) query.set('document_id', String(source.id));
          else if (group) query.set('group_id', group);
          current = await prototypeRequest(`${base}/upload?${query}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: file,
            timeoutMs: 1800000,
            signal: abort.current.signal,
          });
          completed++;
          if (!abort.current.signal.aborted) onSaved(current, false);
        }
        if (!abort.current.signal.aborted) onSaved(current, true);
      } else {
        const payload = {
          kind,
          name: name.trim(),
          description,
          group_id: group ? Number(group) : null,
          revision: library.revision,
          ...(kind === 'LINK'
            ? { url: prototypeUrl(url) }
            : { git, selected_paths: selected, commit: scope!.commit }),
        };
        const value = await prototypeRequest(source ? `${base}/${source.id}` : base, {
          method: source ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
          signal: abort.current.signal,
          timeoutMs: 120000,
        });
        if (!abort.current.signal.aborted) onSaved(value, true);
      }
    } catch (e) {
      if (!abort.current.signal.aborted) {
        if (kind === 'FILE') setFiles((old) => old.slice(completed));
        setError(
          `${completed ? `已保存${completed}个文件。` : ''}${prototypeError(e, onSessionEnd)}`,
        );
      }
    } finally {
      pending.current = false;
      if (!abort.current.signal.aborted) setBusy(false);
    }
  }
  return (
    <CaseDialog
      title={
        directory
          ? source
            ? '上传目录新版本'
            : '上传本地目录'
          : source
            ? kind === 'FILE'
              ? `更新${fileLabel}版本`
              : '编辑实时来源'
            : kind === 'GITHUB'
              ? '从 GitHub 添加原型'
              : kind === 'LINK'
                ? '添加原型链接'
                : `上传原型${fileLabel}`
      }
      busy={busy}
      onClose={onClose}
      wide
      className="prototype-editor-dialog"
    >
      <Form
        className="prototype-editor-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="prototype-editor-content">
          <fieldset className="prototype-form-section">
            <legend>资料信息</legend>
            <div className="case-form-grid">
              <label className="form-field">
                资料名称
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={200}
                  required={kind !== 'FILE'}
                  disabled={busy}
                  placeholder="例如：订单管理页面；文件可沿用文件名"
                />
              </label>
              <FormSelect
                label="资料分组"
                value={group}
                disabled={busy || (!!source && kind === 'FILE')}
                onChange={setGroup}
                options={[
                  { value: '', label: '未分组' },
                  ...library.groups.map((g) => ({ value: String(g.id), label: g.name })),
                ]}
              />
              <label className="form-field span2">
                页面 / 交互说明
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={2000}
                  disabled={busy}
                  rows={2}
                  placeholder="补充这份原型包含的页面或使用说明"
                />
              </label>
            </div>
          </fieldset>
          {kind === 'LINK' && (
            <fieldset className="prototype-form-section">
              <legend>原型链接</legend>
              <label className="form-field">
                原型链接
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  maxLength={8192}
                  required
                  disabled={busy}
                  placeholder="https://…"
                />
              </label>
              <p className="hint mt">保存后可加载网页预览；实时页面不等于已保存快照。</p>
            </fieldset>
          )}
          {kind === 'GITHUB' && (
            <>
              <fieldset className="prototype-form-section">
                <legend>读取范围</legend>
                <div className="prototype-section-caption">
                  <p className="hint">选择本人已授权的项目仓库。</p>
                  <div className="row">
                    <Link to="/platform">配置 GitHub 连接</Link>
                    <Link to="/project">管理项目仓库</Link>
                  </div>
                </div>
                <div className="case-form-grid">
                  <FormSelect
                    label="我的 GitHub 连接"
                    value={connection}
                    required
                    disabled={busy}
                    options={[
                      { value: '', label: '请选择连接' },
                      ...connections.map((c) => ({ value: String(c.id), label: c.name })),
                    ]}
                    onChange={(v) => {
                      setConnection(v);
                      setRepository('');
                      reset();
                    }}
                  />
                  <FormSelect
                    label="项目已关联仓库"
                    value={repository}
                    required
                    disabled={busy}
                    options={[
                      { value: '', label: '请选择已授权仓库' },
                      ...repos.map((r) => ({ value: String(r.id), label: r.name })),
                    ]}
                    onChange={(v) => {
                      setRepository(v);
                      setBranch(repos.find((r) => r.id === Number(v))?.branch || 'main');
                      reset();
                    }}
                  />
                  <label className="form-field">
                    跟踪分支
                    <input
                      value={branch}
                      maxLength={255}
                      required
                      disabled={busy}
                      onChange={(e) => {
                        setBranch(e.target.value);
                        reset();
                      }}
                    />
                  </label>
                  <label className="form-field">
                    原型目录或文件（选填）
                    <input
                      value={path}
                      maxLength={500}
                      disabled={busy}
                      onChange={(e) => {
                        setPath(e.target.value);
                        reset();
                      }}
                      placeholder="留空读取整个仓库的原型文件"
                    />
                  </label>
                </div>
              </fieldset>
              <fieldset className="prototype-form-section">
                <legend>文件清单</legend>
                <div className="prototype-section-caption">
                  <p className="hint">读取后默认全选，可取消不需要的文件。</p>
                  <button
                    type="button"
                    className="small"
                    disabled={busy}
                    onClick={() => void scan()}
                  >
                    {busy ? '正在处理…' : '读取文件清单'}
                  </button>
                </div>
                {scope ? (
                  <>
                    <div className="prototype-files-toolbar">
                      <span className="hint">
                        提交 <span className="mono">{scope.commit.slice(0, 7)}</span>
                      </span>
                      <div className="row">
                        <span className="hint" role="status">
                          已选 {selected.length} / {scope.files.length}
                        </span>
                        <button
                          type="button"
                          className="small"
                          disabled={
                            busy || !scope.files.length || selected.length === scope.files.length
                          }
                          onClick={() => setSelected(scope.files.map((file) => file.path))}
                        >
                          全选
                        </button>
                        <button
                          type="button"
                          className="ghost small"
                          disabled={busy || !selected.length}
                          onClick={() => setSelected([])}
                        >
                          清空
                        </button>
                      </div>
                    </div>
                    <div className="prototype-file-list">
                      {scope.files.map((f) => (
                        <label className="prototype-file-row" key={f.path}>
                          <input
                            type="checkbox"
                            disabled={busy}
                            checked={selectedSet.has(f.path)}
                            onChange={(e) =>
                              setSelected((old) =>
                                e.target.checked
                                  ? [...old, f.path]
                                  : old.filter((p) => p !== f.path),
                              )
                            }
                          />
                          <span>{f.path}</span>
                          <small className="hint">{f.path.split('.').pop()?.toUpperCase()}</small>
                        </label>
                      ))}
                    </div>
                    <p className="hint prototype-section-note">
                      保存前会再次核实提交及文件；分支更新时需重新读取。
                    </p>
                  </>
                ) : (
                  <div className="prototype-files-empty">尚未读取文件清单</div>
                )}
              </fieldset>
            </>
          )}
          {directory && (
            <fieldset className="prototype-form-section">
              <legend>{source ? '上传完整目录新版本' : '本地目录'}</legend>
              <p className="hint">
                上传所选文件到平台，保留相对目录结构并在项目内共享。新版不覆盖旧版本和历史分析依据。
              </p>
              <FilePicker
                accept=""
                multiple
                directory
                disabled={busy}
                onChange={(incoming) => {
                  try {
                    const value = selectedDirectory(incoming);
                    setFolder(value);
                    setSelected(value.entries.map((e) => e.path));
                    if (!source && !name.trim()) setName(value.name.slice(0, 200));
                    setError('');
                    directoryRequest.current = null;
                  } catch (e) {
                    setError(prototypeError(e, onSessionEnd));
                  }
                }}
              />
              {folder && (
                <>
                  <p className="hint mt" role="status">
                    {folder.name} · 已选{selected.length}/{folder.entries.length}个文件 ·{' '}
                    {folder.entries
                      .filter((e) => selectedSet.has(e.path))
                      .reduce((n, e) => n + e.file.size, 0)
                      .toLocaleString()}
                    字节{busy ? ' · 正在上传并校验…' : ''}
                  </p>
                  <div className="directory-upload-files">
                    <CodeFileTree
                      paths={folder.entries.map((e) => e.path)}
                      selected={selected}
                      onChange={setSelected}
                      disabled={busy}
                    />
                  </div>
                  {!!folder.skipped.length && (
                    <details className="mt">
                      <summary>已排除{folder.skipped.length}个不支持或敏感路径文件</summary>
                      <p className="hint">以下文件不会上传。</p>
                      {folder.skipped.map((path) => (
                        <p className="hint prototype-url" key={path}>
                          {path}
                        </p>
                      ))}
                    </details>
                  )}
                  {!folder.entries.length && (
                    <p className="form-error" role="alert">
                      目录内没有支持上传的原型文件。
                    </p>
                  )}
                </>
              )}
            </fieldset>
          )}
          {kind === 'FILE' && (
            <fieldset className="prototype-form-section">
              <legend>原型{fileLabel}</legend>
              <div
                className="doc-upload-zone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  addFiles(Array.from(e.dataTransfer.files));
                }}
              >
                <h3>选择或拖入原型{fileLabel}</h3>
                <p className="hint">
                  {html ? 'HTML / HTM' : 'PNG / JPG / WEBP'} ·{' '}
                  {source ? '单个文件生成新版本' : '可多选并继续追加'}
                </p>
                <FilePicker
                  accept={html ? '.html,.htm' : '.png,.jpg,.jpeg,.webp'}
                  multiple={!source}
                  disabled={busy}
                  onChange={addFiles}
                />
                {files.map((f, i) => (
                  <div className="between mt" key={i}>
                    <span className="prototype-url">{f.name}</span>
                    <button
                      type="button"
                      className="ghost small"
                      disabled={busy}
                      aria-label={`移除待上传文件 ${f.name}`}
                      onClick={() => setFiles((old) => old.filter((_, n) => n !== i))}
                    >
                      移除
                    </button>
                  </div>
                ))}
              </div>
            </fieldset>
          )}
          <p className="hint prototype-section-note">
            {directory
              ? '仅保存勾选文件，上传不自动调用 AI。分析时可选择固定版本和其中的文件。'
              : kind === 'FILE'
                ? html
                  ? '原件完整保存，提供源码预览与下载；不执行脚本、不读取外部依赖。上传不自动调用 AI。'
                  : '原件完整保存，新版本不覆盖历史文件。'
                : '保存实时来源配置，不手动生成资料版本；链接预览不是页面快照。'}
          </p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
        <div className="row prototype-editor-footer">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <button className="primary" disabled={busy}>
            {directory ? (busy ? '正在上传并校验…' : '上传目录') : busy ? '正在处理…' : '保存资料'}
          </button>
        </div>
      </Form>
    </CaseDialog>
  );
}
