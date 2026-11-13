import { useEffect, useState } from 'react';
import { apiRequest } from './api/http';
import { CodeFileTree } from './CodeFileTree';
import { directoryBase, directoryCatalog } from './prototypeDirectory';
import type { DirectoryFile } from './prototypeDirectory';
import { prototypeError } from './prototypeApi';
import { parsePreview } from './documentApi';
import type { DocumentPreview } from './documentApi';

export function PrototypeDirectoryFiles({
  projectId,
  documentId,
  versionId,
  value,
  onChange,
  onSessionEnd,
  disabled = false,
  browse = false,
}: {
  projectId: number;
  documentId: number;
  versionId: number;
  value: string[];
  onChange: (paths: string[]) => void;
  onSessionEnd: () => void;
  disabled?: boolean;
  browse?: boolean;
}) {
  const [files, setFiles] = useState<DirectoryFile[] | null>(null),
    [error, setError] = useState(''),
    [opened, setOpened] = useState(''),
    [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    setFiles(null);
    setError('');
    setOpened('');
    setPreview(null);
    directoryCatalog(projectId, documentId, versionId, c.signal)
      .then((v) => {
        if (!c.signal.aborted) setFiles(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(prototypeError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [projectId, documentId, versionId, onSessionEnd, reload]);
  useEffect(() => {
    if (!opened) return;
    if (/\.html?$/i.test(opened)) {
      setPreview({
        kind: 'unsupported',
        text: 'HTML 预览包含同一目录版本内引用的样式、脚本和图片；外部网络与平台接口不可访问。',
      });
      return;
    }
    const c = new AbortController();
    setPreview(null);
    apiRequest<unknown>(
      directoryBase(projectId, documentId, versionId) +
        '/preview?' +
        new URLSearchParams({ path: opened }),
      { signal: c.signal },
    )
      .then(parsePreview)
      .then((v) => {
        if (!c.signal.aborted) setPreview(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(prototypeError(e, onSessionEnd));
      });
    return () => c.abort();
  }, [opened, projectId, documentId, versionId, onSessionEnd]);
  return (
    <section
      className={`prototype-directory-files${browse ? ' directory-browser' : ''}`}
      aria-label="固定目录版本文件"
    >
      {!files && !error && (
        <p className="hint" role="status">
          正在读取固定版本文件清单…
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}{' '}
          <button
            type="button"
            className="ghost small"
            disabled={disabled}
            onClick={() => setReload((n) => n + 1)}
          >
            重新读取
          </button>
        </p>
      )}
      {files && (
        <>
          <p className="hint">
            {browse
              ? '点击文件名查看原件内容。'
              : '只将勾选文件用于本次分析；未勾选的依赖不会自动发送。'}{' '}
            · 共{files.length}个文件
          </p>
          <CodeFileTree
            paths={files.map((f) => f.path)}
            selected={value}
            onChange={onChange}
            disabled={disabled}
            onPreview={(path) => {
              setError('');
              setOpened(path);
            }}
          />
        </>
      )}
      {opened && (
        <section className="evidence directory-file-preview">
          <div className="between">
            <strong>{opened}</strong>
            <a
              className="action small"
              href={
                directoryBase(projectId, documentId, versionId) +
                '/file?' +
                new URLSearchParams({ path: opened })
              }
            >
              下载文件
            </a>
            {/\.html?$/i.test(opened) && (
              <a
                className="action small"
                target="_blank"
                rel="noopener noreferrer"
                href={
                  directoryBase(projectId, documentId, versionId) +
                  '/browser?' +
                  new URLSearchParams({ path: opened })
                }
              >
                在浏览器打开
              </a>
            )}
          </div>
          {!preview && <p className="hint">正在读取文件…</p>}
          {preview?.kind === 'image' ? (
            <img
              alt={opened}
              src={
                directoryBase(projectId, documentId, versionId) +
                '/file?' +
                new URLSearchParams({ path: opened, inline: 'true' })
              }
            />
          ) : preview?.kind === 'unsupported' ? (
            <p className="hint">{preview.text}</p>
          ) : (
            preview && (
              <>
                <pre>{preview.text}</pre>
                {preview.truncated && (
                  <p className="hint">预览仅显示前100,000字符，下载与分析使用完整文件。</p>
                )}
              </>
            )
          )}
        </section>
      )}
    </section>
  );
}
