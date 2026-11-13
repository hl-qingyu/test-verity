import { Select } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { documentError, libraryRequest, linkKey, parseLinks, parseVersion } from './documentApi';
import type {
  DocumentLibrary,
  DocumentLink,
  DocumentLinks as Links,
  DocumentVersion,
} from './documentApi';
import { MarkdownPreview } from './MarkdownPreview';
import { Icon } from './Icon';

export function DocumentLinks({
  base,
  version,
  text,
  onSessionEnd,
  onOpen,
  onChanged,
}: {
  base: string;
  version: DocumentVersion;
  text: string;
  onSessionEnd: () => void;
  onOpen: (version: DocumentVersion) => void;
  onChanged: () => void;
}) {
  const [links, setLinks] = useState<Links | null>(null),
    [revision, setRevision] = useState(0),
    [error, setError] = useState('');
  const [active, setActive] = useState<DocumentLink | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    apiRequest<unknown>(`${base}/versions/${version.id}/links`, { signal: controller.signal })
      .then(parseLinks)
      .then((data) => {
        if (!controller.signal.aborted) setLinks(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(documentError(e, onSessionEnd));
      });
    return () => controller.abort();
  }, [base, version.id, revision, onSessionEnd]);
  return (
    <>
      <p className="hint">
        点击链接关联项目附件；已关联链接可打开固定版本。不会访问原地址或加载文内图片。
      </p>
      {links && !links.editable && (
        <p className="doc-note">历史版本的关联只读，修改请在当前文档版本中进行。</p>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
          <button className="small" onClick={() => setRevision((n) => n + 1)}>
            重新加载关联
          </button>
        </p>
      )}
      <MarkdownPreview
        text={text}
        renderLink={(href, children) => {
          const entry = links?.links.find((link) => linkKey(link.href) === linkKey(href));
          if (!entry)
            return (
              <span
                className="markdown-link-label"
                title={links ? '此链接暂不支持关联' : '正在读取关联'}
              >
                {children}
              </span>
            );
          const binding = entry.binding;
          return (
            <span className="markdown-bound-link">
              <button
                className="markdown-link-button"
                disabled={!binding && !links?.editable}
                title={
                  binding
                    ? `打开 ${binding.target.filename} · v${binding.target.number}`
                    : '选择平台附件关联'
                }
                onClick={() => (binding ? onOpen(binding.target) : setActive(entry))}
              >
                {children}
              </button>
              <small>
                {binding
                  ? `已关联 · v${binding.target.number}${binding.target.deleted ? ' · 资料已删除' : ''}${binding.inherited ? ' · 已继承' : ''}`
                  : '待关联'}
              </small>
              {binding && binding.latest_number > binding.target.number && (
                <small className="link-update">有新版本 v{binding.latest_number}</small>
              )}
              {binding && links?.editable && (
                <button
                  className="ghost small link-edit"
                  title="修改关联"
                  aria-label={`修改关联：${entry.label}`}
                  onClick={() => setActive(entry)}
                >
                  <Icon name="edit" />
                </button>
              )}
            </span>
          );
        }}
      />
      {active && links && (
        <LinkPicker
          key={active.href}
          base={base}
          sourceVersionId={version.id}
          link={active}
          onSessionEnd={onSessionEnd}
          onClose={() => setActive(null)}
          onOpen={onOpen}
          onSaved={(data) => {
            setLinks(data);
            setActive(null);
            onChanged();
          }}
        />
      )}
    </>
  );
}

function LinkPicker({
  base,
  sourceVersionId,
  link,
  onSessionEnd,
  onClose,
  onOpen,
  onSaved,
}: {
  base: string;
  sourceVersionId: number;
  link: DocumentLink;
  onSessionEnd: () => void;
  onClose: () => void;
  onOpen: (version: DocumentVersion) => void;
  onSaved: (links: Links) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [library, setLibrary] = useState<DocumentLibrary | null>(null),
    [links, setLinks] = useState<Links | null>(null),
    [error, setError] = useState('');
  const [search, setSearch] = useState(''),
    [selected, setSelected] = useState<number | null>(link.binding?.target.document_id || null),
    [versions, setVersions] = useState<DocumentVersion[]>([]),
    [target, setTarget] = useState<number | null>(link.binding?.target.id || null),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [reload, setReload] = useState(0);
  const pending = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    dialog.current?.showModal();
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    Promise.all([
      libraryRequest(base, { signal: controller.signal }),
      apiRequest<unknown>(`${base}/versions/${sourceVersionId}/links`, {
        signal: controller.signal,
      }).then(parseLinks),
    ])
      .then(([lib, list]) => {
        if (!controller.signal.aborted) {
          setLibrary(lib);
          setLinks(list);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(documentError(e, onSessionEnd));
      });
    return () => controller.abort();
  }, [base, sourceVersionId, reload, onSessionEnd]);
  useEffect(() => {
    const controller = new AbortController();
    setVersions([]);
    setLoading(true);
    if (selected === null) {
      setLoading(false);
      return () => controller.abort();
    }
    apiRequest<unknown>(`${base}/${selected}/versions`, { signal: controller.signal })
      .then((value) => {
        if (!Array.isArray(value)) throw new Error('document_response_invalid');
        const rows = value.map(parseVersion).filter((v) => v.id !== sourceVersionId);
        if (rows.some((v) => v.document_id !== selected))
          throw new Error('document_response_invalid');
        if (!controller.signal.aborted) {
          setVersions(rows);
          setTarget((id) => (rows.some((v) => v.id === id) ? id : rows[0]?.id || null));
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(documentError(e, onSessionEnd));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [base, selected, reload, sourceVersionId, onSessionEnd]);
  const address = linkKey(link.href),
    filename = address.split(/[\\/]/).pop()?.split(/[?#]/)[0] || '';
  const docs = [...(library?.documents || [])]
    .filter(
      (d) =>
        d.current.id !== sourceVersionId &&
        d.current.filename.toLowerCase().includes(search.toLowerCase()),
    )
    .sort(
      (a, b) => Number(b.current.filename === filename) - Number(a.current.filename === filename),
    );
  const current = links?.links.find((entry) => linkKey(entry.href) === linkKey(link.href))?.binding;
  async function save() {
    if (!links || !target || !versions.some((v) => v.id === target) || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      const data = parseLinks(
        await apiRequest<unknown>(`${base}/versions/${sourceVersionId}/links`, {
          method: 'POST',
          body: JSON.stringify({
            href: link.href,
            target_version_id: target,
            revision: links.revision,
          }),
        }),
      );
      if (alive.current) onSaved(data);
    } catch (e) {
      if (alive.current) setError(documentError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="account-dialog document-dialog link-picker"
      aria-label="关联平台附件"
      onCancel={(e) => {
        e.preventDefault();
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <header className="doc-dialog-head">
        <h2>关联平台附件</h2>
        <button className="ghost small" aria-label="关闭关联窗口" disabled={busy} onClick={onClose}>
          ×
        </button>
      </header>
      <div className="panel-pad">
        <strong>{link.label}</strong>
        <p className="hint link-original-address">原链接：{address}</p>
        {current && (
          <div className="doc-note">
            当前关联：{current.target.filename} · v{current.target.number}
            {current.latest_number > current.target.number && (
              <span>（有新版本 v{current.latest_number}，不会自动替换）</span>
            )}
            <button
              className="small"
              disabled={busy}
              onClick={() => {
                onClose();
                onOpen(current.target);
              }}
            >
              查看关联原文
            </button>
          </div>
        )}
        <label className="form-field">
          搜索项目附件
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="按文件名搜索"
            disabled={busy}
          />
        </label>
        <div className="link-candidates" role="group" aria-label="可关联附件">
          {!library ? (
            <p className="hint">正在加载项目附件…</p>
          ) : docs.length ? (
            docs.map((d) => (
              <label key={d.id} className={selected === d.id ? 'selected' : ''}>
                <input
                  type="radio"
                  name="link-target-document"
                  disabled={busy}
                  checked={selected === d.id}
                  onChange={() => {
                    setSelected(d.id);
                    setTarget(null);
                  }}
                />
                <span>
                  <strong>{d.current.filename}</strong>
                  <small>
                    {library.groups.find((g) => g.id === d.group_id)?.name || '未分组'} · 当前 v
                    {d.current.number}
                    {d.current.filename === filename ? ' · 同名推荐' : ''}
                  </small>
                </span>
              </label>
            ))
          ) : (
            <p className="hint">未找到附件，请先在需求资料中上传，再打开链接关联。</p>
          )}
        </div>
        <label className="form-field">
          固定附件版本
          <Select
            className="link-version-select"
            value={target || ''}
            disabled={busy || loading || selected === null}
            onChange={(e) => setTarget(Number(e))}
          >
            <option value="" disabled>
              {loading ? '正在加载版本…' : '请选择版本'}
            </option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.number} · {v.filename} · {new Date(v.created_at).toLocaleString()}
              </option>
            ))}
          </Select>
        </label>
        <p className="hint">
          同名仅用于推荐，需确认后关联。目标上传新版仍保留所选版本；历史来源版本只读。
        </p>
        {links && !links.editable && (
          <p role="alert" className="form-error">
            来源已成为历史版本，不能修改关联。
          </p>
        )}
        {error && (
          <p role="alert" className="form-error">
            {error}
            <button disabled={busy} onClick={() => setReload((n) => n + 1)}>
              刷新关联与附件
            </button>
          </p>
        )}
        <button
          className="primary"
          disabled={
            busy || loading || !links?.editable || !target || !versions.some((v) => v.id === target)
          }
          onClick={() => void save()}
        >
          {busy ? '正在保存…' : '确认关联此版本'}
        </button>
      </div>
    </dialog>
  );
}
