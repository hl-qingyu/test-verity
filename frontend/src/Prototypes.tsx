import { MaterialDeleteDialog } from './MaterialDeleteDialog';
import { useEffect, useRef, useState } from 'react';
import { useMaterialDrag } from './useMaterialDrag';
import { Link } from 'react-router-dom';
import type { Project } from './Projects';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { FormSelect } from './FormSelect';
import { Icon } from './Icon';
import { OriginalPreview } from './Documents';
import { parseVersion } from './documentApi';
import type { DocumentVersion } from './documentApi';
import { PrototypeEditor } from './PrototypeEditor';
import { PrototypeDirectoryFiles } from './PrototypeDirectoryFiles';
import { PrototypeLinkPreview } from './PrototypeLinkPreview';
import {
  parsePrototypeCheck,
  parsePrototypeOptions,
  prototypeError,
  prototypeRequest,
} from './prototypeApi';
import type {
  PrototypeCheck,
  PrototypeConnection,
  PrototypeLibrary,
  PrototypeSource,
} from './prototypeApi';

const kindNames = {
  GITHUB: 'GitHub 原型',
  LINK: '原型链接',
  FILE: '本地原型',
  DIRECTORY: '本地目录',
};
export function Prototypes({
  project,
  onSessionEnd,
  documentId,
}: {
  project: Project | null;
  onSessionEnd: () => void;
  documentId?: number;
}) {
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const base = `/api/projects/${project?.id}/prototypes`,
    documents = `/api/projects/${project?.id}/documents`;
  const [library, setLibrary] = useState<PrototypeLibrary | null>(null),
    [loading, setLoading] = useState(true),
    [options, setOptions] = useState<PrototypeConnection[]>([]),
    [optionsError, setOptionsError] = useState(''),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [reload, setReload] = useState(0),
    [selected, setSelected] = useState<number | null>(documentId ?? null),
    [historical, setHistorical] = useState<DocumentVersion | null>(null),
    [editor, setEditor] = useState<{
      kind: PrototypeSource['kind'];
      html?: boolean;
      source?: PrototypeSource;
    } | null>(null),
    [modal, setModal] = useState<'create' | 'rename' | 'move' | 'history' | null>(null),
    [groupId, setGroupId] = useState(''),
    [groupName, setGroupName] = useState(''),
    [busy, setBusy] = useState(false),
    [history, setHistory] = useState<DocumentVersion[]>([]),
    [modalError, setModalError] = useState(''),
    [connection, setConnection] = useState(''),
    [checkGeneration, setCheckGeneration] = useState(0),
    [check, setCheck] = useState<PrototypeCheck | null>(null),
    [checking, setChecking] = useState(false),
    [checkError, setCheckError] = useState('');
  const lifetime = useRef(new AbortController()),
    pending = useRef(false);
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!editor && editorTrigger.current) {
      editorTrigger.current.focus({ preventScroll: true });
      editorTrigger.current = null;
    }
  }, [editor]);
  const {
    dragView,
    suppressClick,
    pointerDown,
    pointerMove,
    pointerUp,
    cancel: cancelDrag,
  } = useMaterialDrag({
    projectId: project?.id,
    disabled: busy || loading || deleteId !== null || !!editor || !!modal,
    onMove: (id, group) => void mutate('move', { document_ids: [id], group_id: group }),
  });
  useEffect(() => {
    const c = new AbortController();
    lifetime.current = c;
    return () => c.abort();
  }, []);
  useEffect(() => {
    if (!project) {
      setLoading(false);
      return;
    }
    const c = new AbortController();
    setLoading(true);
    setError('');
    prototypeRequest(base, { signal: c.signal })
      .then((data) => {
        if (!c.signal.aborted) setLibrary(data);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(prototypeError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [base, project, reload, onSessionEnd]);
  useEffect(() => {
    if (!project) return;
    const c = new AbortController();
    setOptionsError('');
    apiRequest<unknown>(`${base}/options`, { signal: c.signal })
      .then(parsePrototypeOptions)
      .then((v) => {
        if (!c.signal.aborted) setOptions(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setOptions([]);
          setOptionsError(prototypeError(e, onSessionEnd));
        }
      });
    return () => c.abort();
  }, [base, project, reload, onSessionEnd]);
  useEffect(() => {
    if (documentId) {
      setSelected(documentId);
      setHistorical(null);
    }
  }, [documentId]);
  const current =
    library?.sources.find((s) => s.id === selected) ||
    (selected === documentId ? undefined : library?.sources[0]);
  const usable = options.filter((c) => c.repositories.some((r) => r.id === current?.repository_id));
  const connectionId = usable.some((c) => c.id === Number(connection))
    ? Number(connection)
    : usable[0]?.id;
  const currentId = current?.id,
    currentKind = current?.kind,
    currentBranch = current?.branch,
    currentPath = current?.path,
    currentRepository = current?.repository_id;
  useEffect(() => {
    setCheck(null);
    setCheckError('');
    setChecking(false);
    if (!currentId || currentKind !== 'GITHUB' || !connectionId) return;
    const c = new AbortController();
    setChecking(true);
    apiRequest<unknown>(`${base}/${currentId}/check`, {
      method: 'POST',
      body: JSON.stringify({ connection_id: connectionId }),
      signal: c.signal,
      timeoutMs: 120000,
    })
      .then(parsePrototypeCheck)
      .then((data) => {
        if (!c.signal.aborted) {
          setCheck(data);
          setLibrary((old) =>
            old
              ? {
                  ...old,
                  sources: old.sources.map((s) => (s.id === data.source.id ? data.source : s)),
                }
              : old,
          );
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setCheckError(prototypeError(e, onSessionEnd));
      })
      .finally(() => {
        if (!c.signal.aborted) setChecking(false);
      });
    return () => c.abort();
  }, [
    base,
    currentId,
    currentKind,
    currentBranch,
    currentPath,
    currentRepository,
    connectionId,
    checkGeneration,
    onSessionEnd,
  ]);
  async function mutate(action: string, payload: Record<string, unknown>, method = 'POST') {
    if (!library || pending.current) return;
    pending.current = true;
    setBusy(true);
    setModalError('');
    setError('');
    try {
      const value = await prototypeRequest(`${base}/${action}`, {
        method,
        body: JSON.stringify({ ...payload, revision: library.revision }),
        signal: lifetime.current.signal,
      });
      if (!lifetime.current.signal.aborted) {
        setLibrary(value);
        setModal(null);
        setNotice('资料整理已保存。');
      }
    } catch (e) {
      if (!lifetime.current.signal.aborted) {
        const text = prototypeError(e, onSessionEnd);
        setModalError(text);
        setError(text);
      }
    } finally {
      pending.current = false;
      if (!lifetime.current.signal.aborted) setBusy(false);
    }
  }
  async function showHistory() {
    if (!current?.current || pending.current) return;
    setModal('history');
    setHistory([]);
    setModalError('');
    setBusy(true);
    pending.current = true;
    try {
      const result = await apiRequest<unknown>(`${documents}/${current.id}/versions`, {
        signal: lifetime.current.signal,
      });
      if (!Array.isArray(result)) throw new Error('prototype_response_invalid');
      if (!lifetime.current.signal.aborted) setHistory(result.map(parseVersion));
    } catch (e) {
      if (!lifetime.current.signal.aborted) setModalError(prototypeError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (!lifetime.current.signal.aborted) setBusy(false);
    }
  }
  function choose(source: PrototypeSource) {
    setSelected(source.id);
    setHistorical(null);
    setConnection('');
    setCheckGeneration((v) => v + 1);
  }
  if (!project)
    return (
      <section className="panel empty">
        <h2>请先选择项目</h2>
      </section>
    );
  const groups = [...(library?.groups || []), { id: null, name: '未分组' }];
  const image = historical?.document_id === current?.id ? historical : current?.current;
  return (
    <div
      className="documents-page prototypes-page"
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
      <div className="page-head">
        <div>
          <h1>原型资料</h1>
        </div>
        <div className="head-actions">
          <button
            disabled={!library || busy}
            onClick={(e) => {
              editorTrigger.current = e.currentTarget;
              setEditor({ kind: 'DIRECTORY' });
            }}
          >
            <Icon name="folder" />
            上传目录
          </button>
          <button disabled={!library || busy} onClick={() => setEditor({ kind: 'GITHUB' })}>
            <Icon name="github" />从 GitHub 添加
          </button>
          <button disabled={!library || busy} onClick={() => setEditor({ kind: 'LINK' })}>
            添加链接
          </button>
          <button
            disabled={!library || busy}
            onClick={() => setEditor({ kind: 'FILE', html: true })}
          >
            <Icon name="upload" />
            上传 HTML
          </button>
          <button
            disabled={!library || busy}
            className="primary"
            onClick={() => setEditor({ kind: 'FILE' })}
          >
            <Icon name="upload" />
            上传图片
          </button>
        </div>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="hint" role="status">
          {notice}
        </p>
      )}
      <div className="toolbar mt">
        <p className="hint">GitHub/链接为实时来源，上传文件保留版本</p>
      </div>
      {loading && (
        <p role="status" className="hint mt">
          正在加载原型资料…
        </p>
      )}
      {library && (
        <div className="documents-layout mt">
          <section className="panel">
            <div className="panel-head">
              <h2>
                原型清单 <span className="badge">{library.sources.length}</span>
              </h2>
              <button
                className="ghost small"
                disabled={!library || busy}
                onClick={() => {
                  setGroupName('');
                  setGroupId('');
                  setModalError('');
                  setModal('create');
                }}
              >
                创建分组
              </button>
            </div>
            <div className="prototype-list">
              {groups.map((g) => {
                const rows = library.sources.filter((s) => s.group_id === g.id);
                return (
                  <section
                    className={`document-group${dragView?.target === g.id ? ' drop-target' : ''}`}
                    key={g.id ?? 'none'}
                    data-material-group={g.id ?? 'none'}
                    data-material-project={project.id}
                  >
                    <div className="prototype-group-head">
                      <strong>
                        {g.name} <span className="hint">{rows.length}</span>
                      </strong>
                      {g.id && (
                        <button
                          className="ghost small"
                          disabled={busy}
                          aria-label={`修改分组 ${g.name}`}
                          onClick={() => {
                            setGroupId(String(g.id));
                            setGroupName(g.name);
                            setModalError('');
                            setModal('rename');
                          }}
                        >
                          <Icon name="edit" />
                        </button>
                      )}
                    </div>
                    {!rows.length && (
                      <p className="hint prototype-group-empty">
                        {dragView?.target === g.id ? '松开移入此分组' : '暂无资料，可拖入文件'}
                      </p>
                    )}
                    {rows.map((s, i) => (
                      <div
                        className={`document-row ${current?.id === s.id ? 'selected' : ''}${dragView?.id === s.id ? ' dragging' : ''}`}
                        key={s.id}
                        title="拖动资料到目标分组"
                        onPointerDown={(e) => pointerDown(e, s)}
                        onPointerMove={pointerMove}
                        onPointerUp={pointerUp}
                        onPointerCancel={cancelDrag}
                        onLostPointerCapture={cancelDrag}
                      >
                        <button className="document-open" onClick={() => choose(s)}>
                          <span className="prototype-item-name">
                            <Icon
                              name={
                                s.kind === 'GITHUB' ? 'github' : s.kind === 'LINK' ? 'plug' : 'file'
                              }
                            />
                            <strong>{s.name}</strong>
                          </span>
                          <span className="hint">
                            {kindNames[s.kind]} · {s.current ? `v${s.current.number}` : '实时资料'}
                          </span>
                        </button>
                        <div className="doc-order">
                          <button
                            className="ghost small"
                            aria-label={`上移 ${s.name}`}
                            disabled={busy || i === 0}
                            onClick={() =>
                              void mutate('reorder', { document_id: s.id, direction: -1 })
                            }
                          >
                            ↑
                          </button>
                          <button
                            className="ghost small"
                            aria-label={`下移 ${s.name}`}
                            disabled={busy || i === rows.length - 1}
                            onClick={() =>
                              void mutate('reorder', { document_id: s.id, direction: 1 })
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
            </div>
          </section>
          <section className="panel doc-preview-panel">
            {current ? (
              <>
                <div className="panel-head">
                  <div>
                    <h2>{current.name}</h2>
                    <p className="hint">
                      {kindNames[current.kind]} ·{' '}
                      {['FILE', 'DIRECTORY'].includes(current.kind)
                        ? `v${image?.number}${historical ? ' · 历史文件' : ''}`
                        : '实时资料'}
                    </p>
                  </div>
                  <div className="row">
                    {['FILE', 'DIRECTORY'].includes(current.kind) && image && (
                      <a
                        className="action small"
                        href={
                          current.kind === 'DIRECTORY'
                            ? `${base}/directories/${current.id}/versions/${image.id}/archive`
                            : `${documents}/versions/${image.id}/file`
                        }
                      >
                        {current.kind === 'DIRECTORY' ? '下载目录包' : '下载原件'}
                      </a>
                    )}
                    {['FILE', 'DIRECTORY'].includes(current.kind) && (
                      <button className="small" disabled={busy} onClick={() => void showHistory()}>
                        历史版本
                      </button>
                    )}
                    <button
                      className="small"
                      disabled={busy}
                      onClick={() => {
                        setGroupId(String(current.group_id || ''));
                        setModalError('');
                        setModal('move');
                      }}
                    >
                      整理分组
                    </button>
                    <button
                      className="primary small"
                      disabled={busy}
                      onClick={(e) => {
                        if (current.kind === 'DIRECTORY') editorTrigger.current = e.currentTarget;
                        setEditor({
                          kind: current.kind,
                          source: current,
                          html: ['html', 'htm'].includes(current.current?.extension || ''),
                        });
                      }}
                    >
                      {current.kind === 'DIRECTORY'
                        ? '上传目录新版本'
                        : current.kind === 'FILE'
                          ? '更新文件版本'
                          : '编辑来源'}
                    </button>
                    <button
                      className="small danger"
                      disabled={busy || checking}
                      onClick={() => setDeleteId(current.id)}
                    >
                      <Icon name="trash" />
                      删除资料
                    </button>
                  </div>
                </div>
                <section className="prototype-description">
                  <h3>页面 / 交互说明</h3>
                  <p>{current.description || '尚未填写页面说明'}</p>
                </section>
                {current.kind === 'LINK' && current.url && (
                  <PrototypeLinkPreview
                    key={`${current.id}:${current.url}`}
                    name={current.name}
                    url={current.url}
                  />
                )}
                {current.kind === 'FILE' && image && (
                  <OriginalPreview
                    base={documents}
                    version={image}
                    onOpen={setHistorical}
                    onLinksChanged={() => {}}
                    onSessionEnd={onSessionEnd}
                    readOnly
                  />
                )}
                {current.kind === 'DIRECTORY' && image && (
                  <div className="panel-pad">
                    <PrototypeDirectoryFiles
                      key={`${current.id}:${image.id}`}
                      projectId={project.id}
                      documentId={current.id}
                      versionId={image.id}
                      value={[]}
                      onChange={() => {}}
                      onSessionEnd={onSessionEnd}
                      browse
                    />
                  </div>
                )}
                {current.kind === 'GITHUB' && (
                  <div className="panel-pad prototype-git-detail">
                    <section
                      className={`prototype-update-status ${check?.changed || checkError ? 'attention' : ''}`}
                      aria-live="polite"
                    >
                      <div role="status">
                        <Icon name={checkError ? 'alert' : check?.changed ? 'branch' : 'info'} />
                        <div>
                          <strong>
                            {checking
                              ? '正在检查 GitHub 更新…'
                              : checkError
                                ? `检查失败，无法判断是否有更新：${checkError}`
                                : check?.changed
                                  ? `发现新提交 ${check.source.latest_commit?.slice(0, 7)}，当前来源已跟随更新。`
                                  : check
                                    ? '当前分支与最近记录一致，没有新提交。'
                                    : !connectionId
                                      ? '当前账号尚无可读取此仓库的连接。'
                                      : '点击资料时检查分支更新。'}
                          </strong>
                          <p className="hint">
                            {current.checked_at
                              ? `最近成功检查：${new Date(current.checked_at).toLocaleString()}`
                              : '尚无成功检查记录'}
                          </p>
                        </div>
                      </div>
                      <button
                        className="small"
                        disabled={checking || !connectionId}
                        onClick={() => setCheckGeneration((v) => v + 1)}
                      >
                        {checking ? '检查中…' : '重新检查'}
                      </button>
                    </section>
                    <dl className="prototype-source-info">
                      <div className="span2">
                        <dt>来源仓库</dt>
                        <dd>{current.repository_name}</dd>
                      </div>
                      <div>
                        <dt>跟踪分支</dt>
                        <dd>{current.branch}</dd>
                      </div>
                      <div>
                        <dt>当前提交</dt>
                        <dd className="mono">{current.latest_commit?.slice(0, 7) || '尚未检查'}</dd>
                      </div>
                      <div>
                        <dt>原型范围</dt>
                        <dd>{current.path || '整个仓库'}</dd>
                      </div>
                      <div>
                        <dt>文件数量</dt>
                        <dd>{current.selected_paths.length} 个文件</dd>
                      </div>
                    </dl>
                    {optionsError && (
                      <p className="form-error" role="alert">
                        {optionsError}
                      </p>
                    )}
                    {usable.length ? (
                      <FormSelect
                        label="本次读取使用的个人连接"
                        value={String(connectionId || '')}
                        onChange={setConnection}
                        options={usable.map((c) => ({ value: String(c.id), label: c.name }))}
                      />
                    ) : (
                      <div className="doc-error mt">
                        本人尚无可读取此项目仓库的连接。<Link to="/platform">配置 GitHub 连接</Link>
                      </div>
                    )}
                    <p className="hint mt">网页快照采集待接入。</p>
                  </div>
                )}
              </>
            ) : (
              <div className="empty">
                <h3>添加第一份原型资料</h3>
                <p>从 GitHub 选择原型范围，或添加链接、图片和本地 HTML。</p>
              </div>
            )}
          </section>
        </div>
      )}
      {dragView && (
        <div
          className="document-drag-ghost"
          style={{
            left: Math.max(0, Math.min(dragView.x + 18, window.innerWidth - 275)),
            top: Math.max(0, Math.min(dragView.y + 16, window.innerHeight - 95)),
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
      {editor && library && (
        <PrototypeEditor
          base={base}
          kind={editor.kind}
          html={editor.html}
          source={editor.source}
          library={library}
          connections={options}
          onSessionEnd={onSessionEnd}
          onClose={() => setEditor(null)}
          onSaved={(v, done) => {
            setLibrary(v);
            if (done) {
              const added = v.sources.filter(
                (source) => !library.sources.some((old) => old.id === source.id),
              );
              setSelected(editor.source?.id || added.at(-1)?.id || selected);
              setEditor(null);
              setHistorical(null);
              setCheckGeneration((n) => n + 1);
              setNotice('原型资料已保存。');
            }
          }}
        />
      )}
      {deleteId !== null && (
        <MaterialDeleteDialog
          base={base}
          id={deleteId}
          onSessionEnd={onSessionEnd}
          onClose={() => setDeleteId(null)}
          onDeleted={() => {
            setLibrary((old) =>
              old ? { ...old, sources: old.sources.filter((s) => s.id !== deleteId) } : old,
            );
            setHistorical(null);
            setDeleteId(null);
            setNotice('原型资料已删除，历史引用保留。');
            setReload((n) => n + 1);
          }}
        />
      )}
      {modal && library && (
        <CaseDialog
          title={
            {
              create: '创建原型分组',
              rename: '修改原型分组',
              move: '整理原型分组',
              history: '文件历史版本',
            }[modal]
          }
          busy={busy}
          onClose={() => setModal(null)}
        >
          {modal === 'history' ? (
            <>
              {history.map((v) => (
                <div className="between mt" key={v.id}>
                  <div>
                    <strong>
                      v{v.number} · {v.filename}
                    </strong>
                    <p className="hint">
                      {v.created_by} · {new Date(v.created_at).toLocaleString()}
                    </p>
                  </div>
                  <button
                    className="small"
                    disabled={busy}
                    onClick={() => {
                      setHistorical(v);
                      setModal(null);
                    }}
                  >
                    查看文件
                  </button>
                </div>
              ))}
            </>
          ) : (
            <Form
              onSubmit={(e) => {
                e.preventDefault();
                if (modal === 'move') {
                  if (current)
                    void mutate('move', {
                      document_ids: [current.id],
                      group_id: groupId ? Number(groupId) : null,
                    });
                } else
                  void mutate(
                    modal === 'rename' ? `groups/${groupId}` : 'groups',
                    { name: groupName.trim() },
                    modal === 'rename' ? 'PATCH' : 'POST',
                  );
              }}
            >
              {modal === 'move' ? (
                <FormSelect
                  label="目标分组"
                  value={groupId}
                  onChange={setGroupId}
                  disabled={busy}
                  options={groups.map((g) => ({ value: String(g.id || ''), label: g.name }))}
                />
              ) : (
                <label className="form-field">
                  分组名称
                  <input
                    required
                    maxLength={80}
                    value={groupName}
                    disabled={busy}
                    onChange={(e) => setGroupName(e.target.value)}
                  />
                </label>
              )}
              <div className="row mt">
                <button type="button" disabled={busy} onClick={() => setModal(null)}>
                  取消
                </button>
                <button className="primary" disabled={busy}>
                  保存
                </button>
              </div>
            </Form>
          )}
          {modalError && (
            <p className="form-error" role="alert">
              {modalError}
            </p>
          )}
        </CaseDialog>
      )}
    </div>
  );
}
