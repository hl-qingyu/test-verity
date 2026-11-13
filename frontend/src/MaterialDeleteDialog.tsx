import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import { documentError, parseMaterialDeletion, parseMaterialDeleted } from './documentApi';
import type { MaterialDeletion } from './documentApi';

export function MaterialDeleteDialog({
  base,
  id,
  onClose,
  onDeleted,
  onSessionEnd,
}: {
  base: string;
  id: number;
  onClose: () => void;
  onDeleted: () => void;
  onSessionEnd: () => void;
}) {
  const [info, setInfo] = useState<MaterialDeletion | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0);
  const pending = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    const c = new AbortController();
    setInfo(null);
    setError('');
    apiRequest<unknown>(`${base}/${id}/deletion`, { signal: c.signal })
      .then(parseMaterialDeletion)
      .then((value) => {
        if (value.id !== id) throw new Error('document_response_invalid');
        if (!c.signal.aborted) setInfo(value);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(documentError(e, onSessionEnd));
      });
    return () => {
      alive.current = false;
      c.abort();
    };
  }, [base, id, reload, onSessionEnd]);
  async function remove() {
    if (!info || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      parseMaterialDeleted(
        await apiRequest<unknown>(`${base}/${id}/delete`, {
          method: 'POST',
          body: JSON.stringify({ revision: info.revision, confirmed: true }),
        }),
        id,
      );
      if (alive.current) onDeleted();
    } catch (e) {
      if (alive.current) setError(documentError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return (
    <CaseDialog title="确认删除资料" busy={busy} onClose={onClose}>
      {!info && !error && <p role="status">正在核对资料及引用…</p>}
      {info && (
        <>
          <p>确定删除「{info.name}」吗？</p>
          <p className="hint">
            共{info.versions}个文件版本，当前被{info.requirement_references}条验收点引用，有
            {info.link_references}条附件关联记录（含历史），被{info.risk_report_references || 0}
            份风险报告引用。
          </p>
          <p className="doc-note">
            删除后不再出现在资料列表和新建来源选择中。原文件、版本及已有引用保留，历史依据仍可查看并标记“资料已删除”。本期没有恢复入口。
          </p>
          {info.kind !== 'FILE' && (
            <p className="hint">
              仅删除平台来源记录，不修改远端链接或GitHub文件，并停止平台更新检查。
            </p>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <div className="row">
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
        {error && (
          <button disabled={busy} onClick={() => setReload((n) => n + 1)}>
            重新核对
          </button>
        )}
        <button
          className="danger"
          disabled={busy || !info || !!error}
          onClick={() => void remove()}
        >
          {busy ? '正在删除…' : '确认删除'}
        </button>
      </div>
    </CaseDialog>
  );
}
