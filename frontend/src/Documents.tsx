import { MaterialDeleteDialog } from './MaterialDeleteDialog';
import { FilePicker } from './FilePicker';
import { Form } from './Form';
import { useEffect, useRef, useState } from 'react';
import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import type { ReactNode } from 'react';
import { useMaterialDrag } from './useMaterialDrag';
import type { Project } from './Projects';
import { apiRequest } from './api/http';
import { documentError, libraryRequest, parseVersion, parsePreview } from './documentApi';
import type {
  DocumentGroup,
  DocumentLibrary,
  DocumentPreview,
  DocumentVersion,
} from './documentApi';
import { Icon } from './Icon';
import { DocumentLinks } from './DocumentLinks';
import { ImagePreview } from './ImagePreview';
import { OfficePreview } from './OfficePreview';
import { MarkdownPreview } from './MarkdownPreview';

const allowed = '.png,.jpg,.jpeg,.webp,.doc,.docx,.pdf,.xlsx,.xls,.md,.txt';
const fileSize = (size: number) =>
  size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${(size / 1024).toFixed(1)} KB`;

function GroupSelect({
  groups,
  value,
  onChange,
  disabled = false,
}: {
  groups: DocumentGroup[];
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: globalThis.MouseEvent) => {
      if (!ref.current?.contains(e.target as Node) && ref.current) ref.current.open = false;
    };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, []);
  const options = [{ id: null, name: '未分组' }, ...groups];
  return (
    <div className="form-field">
      <span>资料分组（可选）</span>
      <details
        className={`doc-group-select${disabled ? ' disabled' : ''}`}
        ref={ref}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && ref.current) {
            ref.current.open = false;
            ref.current.querySelector('summary')?.focus();
          }
        }}
      >
        <summary
          aria-label="选择资料分组"
          aria-disabled={disabled}
          onClick={(e) => {
            if (disabled) e.preventDefault();
          }}
        >
          {options.find((g) => g.id === value)?.name || '未分组'}
          <span aria-hidden="true">⌄</span>
        </summary>
        <div className="doc-group-options" role="group" aria-label="资料分组选项">
          {options.map((g) => (
            <label key={g.id ?? 'none'} className={g.id === value ? 'selected' : ''}>
              <input
                type="radio"
                name="document-group-choice"
                checked={g.id === value}
                disabled={disabled}
                onChange={() => {
                  onChange(g.id);
                  if (ref.current) {
                    ref.current.open = false;
                    ref.current.querySelector('summary')?.focus();
                  }
                }}
              />
              <span>{g.name}</span>
              <span aria-hidden="true">{g.id === value ? '✓' : ''}</span>
            </label>
          ))}
        </div>
      </details>
    </div>
  );
}

function DocumentDialog({
  title,
  busy,
  onClose,
  children,
}: {
  title: string;
  busy: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="account-dialog document-dialog"
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        if (e.target !== e.currentTarget) return;
        if (!busy) onClose();
      }}
    >
      <header className="doc-dialog-head">
        <h2>{title}</h2>
        <button
          type="button"
          className="ghost small"
          disabled={busy}
          onClick={onClose}
          aria-label="关闭对话框"
        >
          ×
        </button>
      </header>
      {children}
    </dialog>
  );
}

export function OriginalPreview({
  base,
  version,
  onSessionEnd,
  onOpen,
  onLinksChanged,
  readOnly = false,
}: {
  base: string;
  version: DocumentVersion;
  onSessionEnd: () => void;
  onOpen: (version: DocumentVersion) => void;
  onLinksChanged: () => void;
  readOnly?: boolean;
}) {
  const [preview, setPreview] = useState<DocumentPreview | null>(null),
    [url, setUrl] = useState(''),
    [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setPreview(null);
    setUrl('');
    setError('');
    if (['html', 'htm', 'directory'].includes(version.extension)) return () => controller.abort();
    void (async () => {
      try {
        const value = parsePreview(
          await apiRequest<unknown>(`${base}/versions/${version.id}/preview`, {
            signal: controller.signal,
          }),
        );
        if (value.kind === 'image' || value.kind === 'pdf') {
          if (controller.signal.aborted) return;
          setUrl(`${base}/versions/${version.id}/file?inline=true`);
        }
        if (!controller.signal.aborted) setPreview(value);
      } catch (e) {
        if (!controller.signal.aborted) setError(documentError(e, onSessionEnd));
      }
    })();
    return () => {
      controller.abort();
    };
  }, [base, version.id, version.extension, onSessionEnd]);
  if (version.extension === 'directory') {
    const projectId = Number(/^\/api\/projects\/(\d+)\/documents$/.exec(base)?.[1]);
    return projectId ? (
      <div className="panel-pad">
        {version.deleted && <p className="doc-note">资料已删除 · 当前查看保留的历史依据</p>}
        <PrototypeDirectoryFiles
          projectId={projectId}
          documentId={version.document_id}
          versionId={version.id}
          value={[]}
          onChange={() => {}}
          onSessionEnd={onSessionEnd}
          browse
        />
      </div>
    ) : (
      <p className="form-error">无法识别目录资料地址。</p>
    );
  }
  if (['html', 'htm'].includes(version.extension))
    return (
      <div className="panel-pad">
        <a
          className="action"
          href={`${base}/versions/${version.id}/browser`}
          target="_blank"
          rel="noopener noreferrer"
        >
          在浏览器打开 {version.filename}
        </a>
      </div>
    );
  if (error)
    return (
      <p role="alert" className="panel-pad form-error">
        {error}
      </p>
    );
  if (!preview)
    return (
      <p className="panel-pad muted" role="status">
        正在读取原文…
      </p>
    );
  const content = () => {
    if (preview.kind === 'image')
      return (
        <ImagePreview
          url={url}
          name={version.filename}
          onError={() => setError('图片无法显示，请下载原件检查。')}
        />
      );
    if (preview.kind === 'pdf')
      return (
        <div>
          <p className="hint panel-pad">如浏览器无法显示PDF，可点击“下载原件”查看。</p>
          <iframe title={version.filename} src={url} className="doc-pdf" />
        </div>
      );
    if (preview.kind === 'unsupported') return <p className="panel-pad muted">{preview.text}</p>;
    if (preview.kind === 'word' || preview.kind === 'workbook')
      return <OfficePreview preview={preview} />;
    return (
      <article className="doc-original">
        {['docx', 'xlsx'].includes(version.extension) && (
          <p className="doc-note">文字与表格预览，完整排版及图片请查看原件。</p>
        )}
        {version.extension === 'md' && readOnly ? (
          <MarkdownPreview text={preview.text} />
        ) : version.extension === 'md' && preview.text ? (
          <>
            <DocumentLinks
              base={base}
              version={version}
              text={preview.text}
              onSessionEnd={onSessionEnd}
              onOpen={onOpen}
              onChanged={onLinksChanged}
            />
          </>
        ) : (
          <pre>{preview.text || '未提取到可显示的文字，请下载原件查看。'}</pre>
        )}
        {preview.truncated && <p className="doc-note">预览仅显示前100,000字符，原件完整保留。</p>}
      </article>
    );
  };
  return (
    <>
      {preview.deleted && <p className="doc-note">资料已删除 · 当前查看保留的历史依据</p>}
      {content()}
    </>
  );
}

export function Documents({
  project,
  onSessionEnd,
  documentId,
}: {
  project: Project | null;
  onSessionEnd: () => void;
  documentId?: number;
}) {
  const base = `/api/projects/${project?.id}/documents`;
  const [library, setLibrary] = useState<DocumentLibrary | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0),
    [selected, setSelected] = useState<number | null>(documentId ?? null),
    [checked, setChecked] = useState<number[]>([]),
    [historical, setHistorical] = useState<DocumentVersion | null>(null);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [modal, setModal] = useState<'create' | 'rename' | 'upload' | 'move' | 'history' | null>(
      null,
    ),
    [busy, setBusy] = useState(false),
    [group, setGroup] = useState<number | null>(null),
    [groupName, setGroupName] = useState(''),
    [files, setFiles] = useState<File[]>([]),
    [uploadDocument, setUploadDocument] = useState<number | null>(null),
    [history, setHistory] = useState<DocumentVersion[]>([]),
    [fileHover, setFileHover] = useState(false);
  const [modalError, setModalError] = useState('');
  const pending = useRef(false),
    uploadIds = useRef(new Map<File, string>()),
    mounted = useRef(true);
  const {
    dragView,
    suppressClick,
    pointerDown,
    pointerMove,
    pointerUp,
    cancel: cancelDrag,
  } = useMaterialDrag({
    projectId: project?.id,
    disabled: busy || loading || deleteId !== null,
    onMove: (id, group) =>
      void mutate('move', { document_ids: [id], group_id: group }, '文件已移动到目标分组。'),
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!project) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError('');
    libraryRequest(base, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) {
          setLibrary(data);
          setChecked((ids) => ids.filter((id) => data.documents.some((d) => d.id === id)));
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(documentError(e, onSessionEnd));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [base, project, reload, onSessionEnd]);
  useEffect(() => {
    if (documentId) {
      setSelected(documentId);
      setHistorical(null);
    }
  }, [documentId]);
  const current =
    library?.documents.find((d) => d.id === selected) ||
    (selected === documentId ? undefined : library?.documents[0]);
  const version = historical?.document_id === current?.id ? historical : current?.current;
  const groups = [...(library?.groups || []), { id: null, name: '未分组' }];
  async function mutate(
    action: string,
    payload: Record<string, unknown>,
    message: string,
    method = 'POST',
  ) {
    if (!library || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    setModalError('');
    try {
      const data = await libraryRequest(`${base}/${action}`, {
        method,
        body: JSON.stringify({ ...payload, revision: library.revision }),
      });
      if (mounted.current) {
        setLibrary(data);
        setModal(null);
        setNotice(message);
      }
    } catch (e) {
      if (mounted.current) {
        const message = documentError(e, onSessionEnd);
        setError(message);
        setModalError(message);
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  function openUpload(documentId: number | null) {
    setUploadDocument(documentId);
    setFiles([]);
    uploadIds.current.clear();
    setGroup(null);
    setModalError('');
    setModal('upload');
  }
  async function upload() {
    if (!library || pending.current) return;
    if (!files.length) {
      setModalError('请先选择文件。');
      return;
    }
    if (uploadDocument && files.length !== 1) {
      setModalError('上传新版本只能选择一个文件。');
      return;
    }
    if (
      files.some(
        (f) =>
          !f.size || !allowed.split(',').includes('.' + f.name.split('.').pop()?.toLowerCase()),
      )
    ) {
      setModalError('请检查文件：不允许空文件，须使用支持的格式。');
      return;
    }
    pending.current = true;
    setBusy(true);
    setModalError('');
    let data = library,
      completed = 0;
    try {
      for (const file of files) {
        let id = uploadIds.current.get(file);
        if (!id) {
          id = crypto.randomUUID();
          uploadIds.current.set(file, id);
        }
        const query = new URLSearchParams({
          filename: file.name,
          revision: String(data.revision),
          upload_id: id,
        });
        if (uploadDocument) query.set('document_id', String(uploadDocument));
        else if (group !== null) query.set('group_id', String(group));
        data = await libraryRequest(`${base}/upload?${query}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/octet-stream' },
          timeoutMs: 30 * 60 * 1000,
          body: file,
        });
        completed++;
        if (mounted.current) {
          setLibrary(data);
          setNotice(`已保存 ${completed} / ${files.length} 个文件`);
        }
      }
      if (mounted.current) {
        setFiles([]);
        setModal(null);
        setHistorical(null);
        setNotice('文件已保存，历史版本保持不变。');
      }
    } catch (e) {
      if (mounted.current) {
        setFiles(files.slice(completed));
        setModalError(`已保存${completed}个文件。${documentError(e, onSessionEnd)}`);
        setError('上传未全部完成，可关闭弹窗并重新加载资料核对。');
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function showHistory() {
    if (!current) return;
    setModalError('');
    setHistory([]);
    setModal('history');
    setBusy(true);
    try {
      const data = await apiRequest<unknown>(`${base}/${current.id}/versions`);
      if (!Array.isArray(data)) throw new Error('document_response_invalid');
      if (mounted.current) setHistory(data.map(parseVersion));
    } catch (e) {
      if (mounted.current) setModalError(documentError(e, onSessionEnd));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  if (!project)
    return (
      <section className="panel panel-pad">
        <h2>请选择项目</h2>
      </section>
    );
  return (
    <section
      className="documents-page"
      onKeyDownCapture={(e) => {
        suppressClick.current = false;
        if (e.key === 'Escape') cancelDrag();
      }}
      onPointerDownCapture={() => {
        suppressClick.current = false;
      }}
      onClickCapture={(e) => {
        if (suppressClick.current) {
          suppressClick.current = false;
          e.preventDefault();
          e.stopPropagation();
        }
      }}
    >
      <header className="page-head">
        <div>
          <h1>需求资料</h1>
        </div>
        <div className="row">
          <button
            disabled={busy || loading || !library}
            onClick={() => {
              setGroupName('');
              setModalError('');
              setModal('create');
            }}
          >
            <Icon name="plus" />
            创建分组
          </button>
          <button
            className="primary"
            disabled={busy || loading || !library}
            onClick={() => openUpload(null)}
          >
            <Icon name="upload" />
            上传需求文件
          </button>
        </div>
      </header>
      <p className="doc-note">拖动文件或勾选后批量切换分组。</p>
      {error && (
        <div role="alert" className="doc-error">
          {error}
          <button disabled={busy || loading} onClick={() => setReload((v) => v + 1)}>
            重新加载
          </button>
        </div>
      )}
      {notice && (
        <p role="status" className="account-notice">
          {notice}
        </p>
      )}
      <div className="toolbar">
        <span>已选 {checked.length} 份资料</span>
        <div className="row">
          <button
            className="small"
            disabled={!checked.length || busy}
            onClick={() => setChecked([])}
          >
            清空选择
          </button>
          <button
            className="small"
            disabled={!checked.length || busy || loading}
            onClick={() => {
              setGroup(null);
              setModalError('');
              setModal('move');
            }}
          >
            整理所选分组
          </button>
          <button
            className="small"
            disabled={!checked.length}
            onClick={() => setNotice('需求分析尚未接入，当前不会发送资料或生成分析结论。')}
          >
            <Icon name="spark" />
            分析所选资料 · 待接入
          </button>
        </div>
      </div>
      {loading && !library ? (
        <p role="status" className="panel-pad">
          正在加载资料…
        </p>
      ) : (
        <div className={`documents-layout${busy ? ' is-busy' : ''}`}>
          <section className="panel">
            <div className="panel-head">
              <h2>
                附件 <span className="muted">{library?.documents.length || 0}</span>
              </h2>
            </div>
            {groups.map((g) => {
              const docs = library?.documents.filter((d) => d.group_id === g.id) || [];
              const target = dragView?.target === g.id;
              return (
                <section
                  key={g.id ?? 'none'}
                  className={`document-group${target ? ' drop-target' : ''}`}
                  data-material-group={g.id ?? 'none'}
                  data-material-project={project.id}
                >
                  <header>
                    <div className="document-group-heading">
                      <strong>{g.name}</strong>
                      {g.id !== null && (
                        <button
                          className="ghost small"
                          disabled={busy || loading}
                          aria-label={`编辑分组名称：${g.name}`}
                          title="编辑分组名称"
                          onClick={() => {
                            setGroup(g.id);
                            setGroupName(g.name);
                            setModalError('');
                            setModal('rename');
                          }}
                        >
                          <Icon name="edit" />
                        </button>
                      )}
                    </div>
                    <span>
                      {target ? '松开，移入此分组' : `${docs.length} 份资料 · 可拖入文件`}
                    </span>
                  </header>
                  {!docs.length && (
                    <div className="doc-group-empty">
                      {target ? '松开即可移动' : '暂无文件，可将文件拖到这里'}
                    </div>
                  )}
                  {docs.map((doc, i) => (
                    <div
                      key={doc.id}
                      className={`document-row${current?.id === doc.id ? ' selected' : ''}${dragView?.id === doc.id ? ' dragging' : ''}`}
                      onPointerDown={(e) =>
                        pointerDown(e, {
                          id: doc.id,
                          group_id: doc.group_id,
                          name: doc.current.filename,
                        })
                      }
                      onPointerMove={pointerMove}
                      onPointerUp={pointerUp}
                      onPointerCancel={cancelDrag}
                      onLostPointerCapture={cancelDrag}
                    >
                      <span className="doc-grip" aria-hidden="true">
                        ⠿
                      </span>
                      <label>
                        <span className="sr-only">选择 {doc.current.filename}</span>
                        <input
                          type="checkbox"
                          checked={checked.includes(doc.id)}
                          disabled={busy}
                          onChange={(e) =>
                            setChecked((ids) =>
                              e.target.checked
                                ? [...ids, doc.id]
                                : ids.filter((id) => id !== doc.id),
                            )
                          }
                        />
                      </label>
                      <button
                        className="document-open"
                        onClick={() => {
                          setSelected(doc.id);
                          setHistorical(null);
                        }}
                      >
                        <span className="hint">
                          {i + 1}. {doc.current.extension.toUpperCase()} · v{doc.current.number}
                        </span>
                        <strong>{doc.current.filename}</strong>
                        <span className="hint">{fileSize(doc.current.size)}</span>
                      </button>
                      <div className="doc-order">
                        <button
                          aria-label={`上移 ${doc.current.filename}`}
                          disabled={i === 0 || busy || loading}
                          onClick={() =>
                            void mutate(
                              'reorder',
                              { document_id: doc.id, direction: -1 },
                              '资料顺序已更新。',
                            )
                          }
                        >
                          ↑
                        </button>
                        <button
                          aria-label={`下移 ${doc.current.filename}`}
                          disabled={i === docs.length - 1 || busy || loading}
                          onClick={() =>
                            void mutate(
                              'reorder',
                              { document_id: doc.id, direction: 1 },
                              '资料顺序已更新。',
                            )
                          }
                        >
                          ↓
                        </button>
                      </div>
                    </div>
                  ))}
                </section>
              );
            })}
          </section>
          <section className="panel doc-preview-panel">
            {current && version ? (
              <>
                <header className="panel-head">
                  <div>
                    <h2>{version.filename}</h2>
                    <p className="hint">
                      {groups.find((g) => g.id === current.group_id)?.name} · v{version.number}
                      {version.id !== current.current.id ? ' · 历史版本' : ''} ·{' '}
                      {fileSize(version.size)}
                    </p>
                    <p className="hint">
                      {version.created_by} · {new Date(version.created_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="row">
                    <button className="small" disabled={busy} onClick={() => void showHistory()}>
                      历史版本
                    </button>
                    <button
                      className="small"
                      disabled={busy || loading}
                      onClick={() => openUpload(current.id)}
                    >
                      上传新版本
                    </button>
                    <button
                      className="small danger"
                      disabled={busy || loading}
                      onClick={() => setDeleteId(current.id)}
                    >
                      <Icon name="trash" />
                      删除资料
                    </button>
                    <a className="action small" href={`${base}/versions/${version.id}/file`}>
                      下载原件
                    </a>
                  </div>
                </header>
                <OriginalPreview
                  key={version.id}
                  base={base}
                  version={version}
                  onSessionEnd={onSessionEnd}
                  onOpen={(target) => {
                    setSelected(target.document_id);
                    setHistorical(target);
                  }}
                  onLinksChanged={() => setReload((n) => n + 1)}
                />
              </>
            ) : (
              <div className="empty">
                <Icon name="file" />
                <h2>上传第一份需求资料</h2>

                <button disabled={busy || loading || !library} onClick={() => openUpload(null)}>
                  选择文件
                </button>
              </div>
            )}
          </section>
        </div>
      )}
      {dragView && (
        <div
          className="document-drag-ghost"
          style={{
            left: Math.min(dragView.x + 18, window.innerWidth - 275),
            top: Math.min(dragView.y + 16, window.innerHeight - 95),
          }}
        >
          <Icon name="file" />
          <div>
            <strong>{dragView.name}</strong>
            <span>
              {dragView.target === undefined
                ? '拖到目标分组后松开'
                : `松开移入「${groups.find((g) => g.id === dragView.target)?.name}」`}
            </span>
          </div>
        </div>
      )}
      {deleteId !== null && (
        <MaterialDeleteDialog
          base={base}
          id={deleteId}
          onSessionEnd={onSessionEnd}
          onClose={() => setDeleteId(null)}
          onDeleted={() => {
            setLibrary((old) =>
              old ? { ...old, documents: old.documents.filter((d) => d.id !== deleteId) } : old,
            );
            setChecked((ids) => ids.filter((id) => id !== deleteId));
            setHistorical(null);
            setDeleteId(null);
            setNotice('资料已删除，历史版本和引用依据保留。');
            setReload((n) => n + 1);
          }}
        />
      )}
      {modal && (
        <DocumentDialog
          title={
            {
              create: '创建资料分组',
              rename: '修改分组名称',
              upload: uploadDocument ? '上传文件新版本' : '上传需求资料',
              move: '整理资料分组',
              history: '文件历史版本',
            }[modal]
          }
          busy={busy}
          onClose={() => setModal(null)}
        >
          <div className="panel-pad">
            {(modal === 'create' || modal === 'rename') && (
              <Form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (modal === 'rename')
                    void mutate(
                      `groups/${group}`,
                      { name: groupName.trim() },
                      '分组名称已更新。',
                      'PATCH',
                    );
                  else void mutate('groups', { name: groupName.trim() }, '资料分组已创建。');
                }}
              >
                <label className="form-field">
                  分组名称
                  <input
                    autoFocus
                    required
                    maxLength={80}
                    value={groupName}
                    disabled={busy}
                    onChange={(e) => setGroupName(e.target.value)}
                    placeholder="例如：成员管理页面截图"
                  />
                </label>

                <button className="primary" disabled={busy || !groupName.trim()}>
                  {busy ? '正在保存…' : modal === 'rename' ? '保存名称' : '创建分组'}
                </button>
              </Form>
            )}
            {modal === 'move' && (
              <>
                <GroupSelect
                  groups={library?.groups || []}
                  value={group}
                  onChange={setGroup}
                  disabled={busy}
                />
                <p className="hint">将{checked.length}份资料移入此分组。</p>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    void mutate(
                      'move',
                      { document_ids: checked, group_id: group },
                      '所选资料已整理。',
                    )
                  }
                >
                  {busy ? '正在保存…' : '保存分组'}
                </button>
              </>
            )}
            {modal === 'upload' && (
              <>
                {!uploadDocument && (
                  <GroupSelect
                    groups={library?.groups || []}
                    value={group}
                    onChange={setGroup}
                    disabled={busy}
                  />
                )}
                <label
                  className={`doc-upload-zone${fileHover ? ' active' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (!busy) setFileHover(true);
                  }}
                  onDragLeave={() => setFileHover(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setFileHover(false);
                    const incoming = Array.from(e.dataTransfer.files);
                    if (!busy && incoming.length)
                      setFiles((previous) =>
                        uploadDocument ? incoming : [...previous, ...incoming],
                      );
                  }}
                >
                  <Icon name="upload" />
                  <strong>选择文件，或拖放到此处</strong>
                  <span>图片 · Word · PDF · Excel · Markdown · TXT</span>
                  <span>
                    分块上传，原件完整保留
                    {uploadDocument ? ' · 仅选择一个新版本文件' : ' · 可一次多选，也可继续添加'}
                  </span>
                  <FilePicker
                    accept={allowed}
                    multiple={!uploadDocument}
                    disabled={busy}
                    onChange={(e) => {
                      const incoming = e;
                      if (incoming.length)
                        setFiles((previous) =>
                          uploadDocument ? incoming : [...previous, ...incoming],
                        );
                    }}
                  />
                </label>
                <ul className="doc-upload-list">
                  {files.map((f, i) => (
                    <li key={`${f.name}-${i}`}>
                      <span className="doc-upload-filename">{f.name}</span>
                      <span>{fileSize(f.size)}</span>
                      <button
                        type="button"
                        className="ghost small"
                        disabled={busy}
                        title="移除待上传文件"
                        aria-label={`移除待上传文件：${f.name}`}
                        onClick={() => {
                          setFiles((previous) => previous.filter((_, index) => index !== i));
                          if (!files.some((other, index) => index !== i && other === f))
                            uploadIds.current.delete(f);
                        }}
                      >
                        <Icon name="trash" />
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="hint">文件保存在本项目，上传不调用AI。</p>
                <button
                  className="primary"
                  disabled={busy || !files.length}
                  onClick={() => void upload()}
                >
                  {busy ? '正在保存文件…' : '上传并保存'}
                </button>
              </>
            )}
            {modal === 'history' && (
              <>
                {busy ? (
                  <p role="status">正在读取历史版本…</p>
                ) : (
                  history.map((v) => (
                    <div className="document-version" key={v.id}>
                      <div>
                        <strong>
                          v{v.number} {v.id === current?.current.id ? '· 当前版本' : ''}
                        </strong>
                        <p>{v.filename}</p>
                        <span className="hint">
                          {v.created_by} · {new Date(v.created_at).toLocaleString()}
                        </span>
                      </div>
                      <button
                        onClick={() => {
                          setHistorical(v);
                          setModal(null);
                        }}
                      >
                        查看原文
                      </button>
                    </div>
                  ))
                )}
              </>
            )}
            {modalError && (
              <p role="alert" className="form-error">
                {modalError}
              </p>
            )}
          </div>
        </DocumentDialog>
      )}
    </section>
  );
}
