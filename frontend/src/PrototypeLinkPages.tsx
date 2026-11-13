import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import './prototype-link-pages.css';

export type LinkSelection = { paths: string[]; snapshot: string };
type Page = { file: string; path: string; url: string };

function parseCatalog(value: unknown): { snapshot: string; pages: Page[] } {
  if (!value || typeof value !== 'object') throw new Error('prototype_link_unsupported');
  const data = value as { snapshot?: unknown; pages?: unknown };
  if (
    typeof data.snapshot !== 'string' ||
    !/^[0-9a-f]{64}$/.test(data.snapshot) ||
    !Array.isArray(data.pages)
  )
    throw new Error('prototype_link_unsupported');
  const pages = data.pages.map((item: unknown) => {
    if (!item || typeof item !== 'object') throw new Error('prototype_link_unsupported');
    const page = item as Record<string, unknown>;
    if (
      typeof page.file !== 'string' ||
      !/^(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\.html$/.test(page.file) ||
      typeof page.path !== 'string' ||
      typeof page.url !== 'string' ||
      !/^(?:https:\/\/prototype\.geekuat\.com\/p\/[A-Za-z0-9]+|http:\/\/127\.0\.0\.1:4173)\/pages\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\.html$/.test(
        page.url,
      ) ||
      !page.url.endsWith(`/pages/${page.file}`)
    )
      throw new Error('prototype_link_unsupported');
    return { file: page.file, path: page.path, url: page.url };
  });
  return { snapshot: data.snapshot, pages };
}

export function PrototypeLinkPages({
  projectId,
  documentId,
  value,
  onChange,
  onSessionEnd,
  disabled = false,
}: {
  projectId: number;
  documentId: number;
  value: LinkSelection;
  onChange: (value: LinkSelection) => void;
  onSessionEnd: () => void;
  disabled?: boolean;
}) {
  const [catalog, setCatalog] = useState<{ snapshot: string; pages: Page[] } | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function read() {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setLoading(true);
    setError('');
    try {
      const next = parseCatalog(
        await apiRequest<unknown>(`/api/projects/${projectId}/prototypes/${documentId}/pages`, {
          signal: current.signal,
        }),
      );
      if (current.signal.aborted) return;
      setCatalog(next);
      if (value.snapshot !== next.snapshot) onChange({ snapshot: next.snapshot, paths: [] });
      setPreview('');
    } catch (reason) {
      if (current.signal.aborted) return;
      if (reason instanceof Error && reason.message === 'not_authenticated') {
        onSessionEnd();
        return;
      }
      setError(
        reason instanceof Error && reason.message === 'prototype_link_unsupported'
          ? '未识别到支持的静态原型页面目录，请检查链接或目录格式。'
          : '页面读取失败，请检查链接或稍后重试。',
      );
    } finally {
      if (!current.signal.aborted) setLoading(false);
    }
  }
  const visible = (catalog?.pages || []).filter((p) =>
    p.path.toLowerCase().includes(search.toLowerCase()),
  );
  const groups = visible.reduce<Record<string, Page[]>>((result, page) => {
    const group = page.path.split(' / ')[0];
    (result[group] ||= []).push(page);
    return result;
  }, {});
  function change(files: string[], checked: boolean) {
    const next = new Set(value.paths);
    for (const file of files) {
      if (checked) next.add(file);
      else next.delete(file);
    }
    onChange({ paths: [...next], snapshot: catalog?.snapshot || '' });
  }
  return (
    <div className="code-file-picker prototype-page-picker">
      <button
        type="button"
        className="small"
        disabled={disabled || loading}
        onClick={() => void read()}
      >
        {loading ? '读取中…' : catalog ? '重新读取页面' : '读取页面'}
      </button>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {catalog && (
        <>
          <label className="form-field">
            搜索页面或路径
            <input value={search} onChange={(e) => setSearch(e.target.value)} disabled={disabled} />
          </label>
          <div className="code-file-picker-toolbar">
            <span className="hint">
              已选 {value.paths.length} / {catalog.pages.length} 个页面
            </span>
            <div className="row">
              <button
                type="button"
                className="small"
                disabled={disabled || !visible.length}
                onClick={() =>
                  change(
                    visible.map((p) => p.file),
                    true,
                  )
                }
              >
                选择当前可见页面
              </button>
              <button
                type="button"
                className="ghost small"
                disabled={disabled || !value.paths.length}
                onClick={() => onChange({ paths: [], snapshot: catalog.snapshot })}
              >
                清空
              </button>
            </div>
          </div>
          <div className="code-file-tree">
            {Object.entries(groups).map(([group, pages]) => (
              <details key={group} className="code-tree-directory">
                <summary>
                  {group} · {pages?.length || 0} 页
                </summary>
                <button
                  type="button"
                  className="ghost small"
                  disabled={disabled}
                  onClick={() =>
                    change(
                      (pages || []).map((p) => p.file),
                      true,
                    )
                  }
                >
                  选择此组
                </button>
                {pages?.map((page) => (
                  <div className="code-tree-file" key={page.file}>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        disabled={disabled}
                        checked={value.paths.includes(page.file)}
                        onChange={(e) => change([page.file], e.target.checked)}
                      />
                      {page.path}
                    </label>
                    <button
                      type="button"
                      className="link"
                      disabled={disabled}
                      onClick={() => setPreview(page.url)}
                    >
                      预览
                    </button>
                  </div>
                ))}
              </details>
            ))}
            {!visible.length && <p className="hint">没有匹配页面。</p>}
          </div>
          {preview && (
            <iframe
              className="prototype-link-frame"
              title="所选原型页面预览"
              src={preview}
              sandbox="allow-scripts allow-same-origin"
              referrerPolicy="no-referrer"
            />
          )}
        </>
      )}
    </div>
  );
}
